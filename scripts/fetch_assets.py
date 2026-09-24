#!/usr/bin/env python3
"""
Download every xStock asset, its proof of reserves, its price, and its
multiplier. Write one merged JSON file.

The asset catalog, the proof of reserves, one quote per symbol, and one
multiplier per symbol come from the xStocks API, through scripts/backed_api.py.
The docstring of each function holds the rule for that step.

Output: data/xstocks-assets.json
  one row per asset that holds a reserve row with a live balance. See
  ASSET_FIELD_ORDER in scripts/sector_map.py for the field list and the order.

The script fetches a quote for every asset whose home market is open. Pass
--force-quotes to call every symbol anyway.

The sector, the industry, the exchange, and the CIK come from
data/ticker_universe.json, through scripts/sector_map.py.

scripts/http_client.py holds the shared HTTP layer. The quote calls share one
pacer. The default gap is 0.25 seconds. Pass --min-interval to change the gap.

The script writes the snapshot twice when the universe refresh runs, because
scripts/ticker_universe.py reads the symbol list. Pass --no-universe-fetch to
skip the refresh.

After the write, the script runs scripts/fetch_logos.py and
scripts/sec_edgar.py. Pass --no-logo-check to skip the logo change check.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/fetch_assets.py
  ./scripts/fetch_assets.py --workers 64
  ./scripts/fetch_assets.py --force-quotes
  ./scripts/fetch_assets.py --no-universe-fetch
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import backed_api
import sector_map

DEFAULT_WORKERS = 8

# The default gap between two quote calls, in seconds.
QUOTE_INTERVAL_SECONDS = 0.25

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
LOGO_SCRIPT = REPO_ROOT / "scripts" / "fetch_logos.py"
EDGAR_SCRIPT = REPO_ROOT / "scripts" / "sec_edgar.py"
UNIVERSE_SCRIPT = REPO_ROOT / "scripts" / "ticker_universe.py"

# One snapshot row. The API node type lives in scripts/backed_api.py.
Record = dict[str, Any]


def merge_records(
    asset_nodes: list[Record], reserve_nodes: list[Record]
) -> tuple[list[Record], list[str], list[str], list[str]]:
    """Join the reserves onto the catalog by symbol.

    Keep one record per asset that holds a reserve row. Return the kept records,
    the symbols dropped for zero shares held, the symbols dropped for a zero
    circulating supply, and the symbols with no reserve entry. A zero count and
    a missing row both mean that no live reserve exists.

    The sector starts empty, because the ticker universe supplies that value.
    apply_sectors() fills it after the price step. The listing country comes
    from the catalog row, so this step fills it. The name loses its xStock mark
    in this step, so the JSON holds the plain name.
    """
    reserves: dict[str, tuple[Any, Any]] = {}
    for node in reserve_nodes:
        symbol = node.get("symbol")
        if isinstance(symbol, str):
            reserves[symbol] = (node.get("sharesHeld"), node.get("circulatingSupply"))

    merged: list[Record] = []
    dropped: list[str] = []
    thin_supply: list[str] = []
    absent: list[str] = []
    for node in asset_nodes:
        symbol = node.get("symbol")
        name = node.get("name")
        if not isinstance(symbol, str) or not isinstance(name, str):
            continue
        name = backed_api.short_name(name)

        shares, supply = reserves.get(symbol, (None, None))
        if shares is None:
            absent.append(symbol)
            continue
        if shares == "0":
            dropped.append(symbol)
            continue
        if supply == "0":
            thin_supply.append(symbol)
            continue

        merged.append(
            {
                "name": name,
                "symbol": symbol,
                "listingCountry": backed_api.listing_country(node),
                "sector": None,
                "industry": None,
                "exchange": None,
                "sharesHeld": shares,
                "circulatingSupply": supply,
            }
        )
    return merged, dropped, thin_supply, absent


def load_last_known(path: Path) -> dict[str, Record]:
    """Read the values of the previous run. This holds the last known value.

    The prices, the multipliers, and the sectors all come from here. The
    previous sector stands when the ticker universe file is absent.
    """
    if not path.is_file():
        return {}

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(
            f"Warning: cannot read the previous prices from {path}: {error}",
            file=sys.stderr,
        )
        return {}

    if not isinstance(rows, list):
        return {}

    known: dict[str, Record] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("symbol"), str):
            known[row["symbol"]] = {
                "price": row.get("price"),
                "priceUpdatedAt": row.get("priceUpdatedAt"),
                "multiplier": row.get("multiplier"),
                "sector": row.get("sector"),
            }
    return known


def apply_values(
    records: list[Record],
    values: list[backed_api.Value],
    last_known: dict[str, Record],
    field: str,
    *,
    stamp_field: str | None = None,
    stamp: str | None = None,
) -> tuple[int, int, int]:
    """Write one value on every record. Return the fresh, kept, and missing counts.

    A value from this run wins, and with stamp_field set the record also takes
    the run time. A null value keeps the value of the previous run when that
    value is a real number, and the record then keeps the time of that run. A
    value that neither source holds reads None.

    The record list holds the symbol order, and the value list matches that
    order. A short value list reads None for the missing tail, so the last known
    value stands. The zip call cannot do this job, because it drops the tail
    rows.
    """
    fresh = 0
    retained = 0
    unavailable = 0

    for index, record in enumerate(records):
        value = values[index] if index < len(values) else None
        source = last_known.get(record["symbol"], {})
        kept = source.get(field)
        stamp_value: str | None = None

        if value is not None:
            record[field] = value
            stamp_value = stamp
            fresh += 1
        elif backed_api.is_number(kept):
            record[field] = kept
            stamp_value = source.get(stamp_field) if stamp_field else None
            retained += 1
        else:
            record[field] = None
            unavailable += 1

        if stamp_field is not None:
            record[stamp_field] = stamp_value

    return fresh, retained, unavailable


def apply_prices(
    records: list[Record],
    quotes: list[backed_api.Value],
    last_known: dict[str, Record],
) -> tuple[int, int, int]:
    """Write the price. A null quote keeps the last known value. Return counts."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return apply_values(
        records, quotes, last_known, "price", stamp_field="priceUpdatedAt", stamp=stamp
    )


def apply_multipliers(
    records: list[Record],
    multipliers: list[backed_api.Value],
    last_known: dict[str, Record],
) -> tuple[int, int, int]:
    """Write the multiplier. A failed call keeps the last known value."""
    return apply_values(records, multipliers, last_known, "multiplier")


def apply_sector_map(
    records: list[Record], last_known: dict[str, Record]
) -> Counter[str]:
    """Join the sector, the industry, the exchange, and the CIK on every record.

    The universe file at data/ticker_universe.json supplies the four values. A
    missing or broken file keeps the value of the previous run. The caller runs
    this step twice: once before the first write, and once after the universe
    refresh, so the second pass reads the fresh universe file.
    """
    return sector_map.apply_sectors(records, sector_map.load_index(), last_known)


def country_counts_line(records: list[Record]) -> str:
    """Return one report line for the listing-country counts.

    The most common country comes first. A tie breaks in code order, so every
    run prints the same line.
    """
    counts: dict[str, int] = {}
    unknown = 0

    for record in records:
        country = record.get("listingCountry")
        if isinstance(country, str) and country:
            counts[country] = counts.get(country, 0) + 1
        else:
            unknown += 1

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    parts = [f"{country} {count}" for country, count in ordered]
    if unknown:
        parts.append(f"{unknown} unknown")
    if not parts:
        return "Country: no value"
    return "Country: " + ", ".join(parts)


def report_symbol_changes(
    records: list[Record], previous: dict[str, Record], has_baseline: bool
) -> list[str]:
    """Print the new and the dropped symbols. Return the new symbol list.

    The previous prices hold the symbol set of the last run. Without a
    baseline the compare is meaningless, so a first run reports no change.
    """
    if not has_baseline:
        print("Symbols: no new, none dropped. No previous snapshot to compare.")
        return []

    known = set(previous)
    current = [record["symbol"] for record in records]
    current_set = set(current)

    new_symbols = [symbol for symbol in current if symbol not in known]
    removed_symbols = [symbol for symbol in previous if symbol not in current_set]

    if not new_symbols and not removed_symbols:
        print("Symbols: no new, none dropped.")
        return []

    if new_symbols:
        print(f"New symbols: {', '.join(new_symbols)}. Fetching their logos...")
    if removed_symbols:
        print(
            f"Dropped symbols: {', '.join(removed_symbols)}. "
            "The logo file stays on disk."
        )
    return new_symbols


def _run_child(script: Path, extra_args: tuple[str, ...] = ()) -> bool:
    """Run one child script from the repo root. Return True on a zero exit code.

    This step prints no warning. The caller prints its own warning, because the
    asset snapshot stays valid and the caller keeps its own exit code.
    """
    command = [sys.executable, str(script), *extra_args]
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return result.returncode == 0


def refresh_edgar_links() -> None:
    """Run the EDGAR link script on the snapshot that the write step saved.

    The script reads the asset snapshot, so the caller runs it after the write.
    """
    print("Refreshing the SEC EDGAR links...")
    if not _run_child(EDGAR_SCRIPT):
        print(
            "Warning: the EDGAR link update failed. "
            "Run scripts/sec_edgar.py to retry.",
            file=sys.stderr,
        )


def refresh_universe() -> bool:
    """Run the ticker universe script on the snapshot that the write step saved.

    The script reads the asset snapshot for its symbol filter, so the caller
    runs it after the first write. Return True on success. A child failure
    returns False, because the sector join then keeps the universe file of the
    previous run.
    """
    print("Refreshing the ticker universe...")
    if _run_child(UNIVERSE_SCRIPT):
        return True

    print(
        "Warning: the ticker universe update failed. "
        "Run scripts/ticker_universe.py to retry.",
        file=sys.stderr,
    )
    return False


def refresh_logos(new_symbols: list[str], check_changes: bool) -> None:
    """Run the logo script for the new symbols and the changed logos."""
    if not new_symbols and not check_changes:
        return

    extra: tuple[str, ...] = ()
    if check_changes:
        print("Checking the saved logos with the server...")
        extra = ("--check-changes",)

    if not _run_child(LOGO_SCRIPT, extra):
        print(
            "Warning: the logo download failed. "
            "Run scripts/fetch_logos.py to retry.",
            file=sys.stderr,
        )


def report_filters(
    dropped: list[str], thin_supply: list[str], absent: list[str], fetched_total: int
) -> None:
    """Print the counts of the rows that the reserve filter removed."""
    removed = len(dropped) + len(thin_supply) + len(absent)
    print(
        f"Filtered out {removed} assets (fetched {fetched_total}): "
        f"{len(dropped)} zero shares held, "
        f"{len(thin_supply)} zero circulating supply, "
        f"{len(absent)} no reserve entry"
    )


def _build_snapshot(
    args: argparse.Namespace,
) -> tuple[list[Record], dict[str, Record], list[str]]:
    """Fetch the catalog, the reserves, the quotes, and the multipliers.

    Return the merged records, the last known values of the previous run, and
    the new symbols of this run.
    """
    # Read the symbol set before the write, so the compare has a baseline.
    has_baseline = OUT_JSON.is_file()
    last_known = load_last_known(OUT_JSON)

    print("Fetching assets...")
    asset_nodes = backed_api.fetch_pages(backed_api.ASSETS_URL, "assets")

    print("Fetching proof of reserves...")
    reserve_nodes = backed_api.fetch_pages(backed_api.RESERVES_URL, "reserves")

    records, dropped, thin_supply, absent = merge_records(asset_nodes, reserve_nodes)
    symbols = [record["symbol"] for record in records]

    closed = (
        set() if args.force_quotes else backed_api.closed_market_symbols(asset_nodes)
    )
    quotes, rate_limited = backed_api.fetch_quotes(
        symbols, closed, workers=args.workers, interval=args.min_interval
    )
    fresh, retained, unavailable = apply_prices(records, quotes, last_known)

    multipliers = backed_api.fetch_multipliers(
        symbols, workers=args.workers, interval=args.min_interval
    )
    multiplier_fresh, multiplier_retained, multiplier_missing = apply_multipliers(
        records, multipliers, last_known
    )

    report_filters(dropped, thin_supply, absent, len(asset_nodes))
    print(f"Prices: {fresh} fresh, {retained} retained, {unavailable} unavailable")
    print(
        f"Multipliers: {multiplier_fresh} fresh, {multiplier_retained} retained, "
        f"{multiplier_missing} unavailable"
    )
    print(f"Rate limited quotes: {rate_limited}")
    new_symbols = report_symbol_changes(records, last_known, has_baseline)
    return records, last_known, new_symbols


def _publish(
    args: argparse.Namespace, records: list[Record], last_known: dict[str, Record]
) -> None:
    """Join the sectors, write the snapshot, and report the counts.

    A missing or broken universe file keeps the sector of the previous run. The
    first write gives the ticker universe script the symbol list of this run.
    The universe file then holds every new symbol, and the sector join runs
    again on that fresh file. The second write holds the result.
    """
    sector_counts = apply_sector_map(records, last_known)
    sector_map.write_assets(records)
    print(f"Wrote {len(records)} assets to {OUT_JSON} (first pass).")

    refreshed = not args.no_universe_fetch and refresh_universe()
    if refreshed:
        print("Joining the sector on the fresh universe...")
        sector_counts = apply_sector_map(records, last_known)
        sector_map.write_assets(records)
        print(
            f"Wrote {len(records)} assets to {OUT_JSON} "
            "(second pass, fresh sectors)."
        )

    print(sector_map.counts_line(sector_counts))
    print(country_counts_line(records))


def run(args: argparse.Namespace) -> int:
    """Fetch everything, merge it, and write the JSON snapshot."""
    records, last_known, new_symbols = _build_snapshot(args)
    _publish(args, records, last_known)

    # The snapshot is on disk now, so the EDGAR links follow the final list.
    refresh_edgar_links()

    refresh_logos(new_symbols, not args.no_logo_check)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch the xStock assets, reserves, and quotes into one JSON file."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel quote calls (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=QUOTE_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between quote calls. Use 0 to stop pacing "
            f"(default: {QUOTE_INTERVAL_SECONDS})."
        ),
    )
    parser.add_argument(
        "--force-quotes",
        action="store_true",
        help="Fetch every quote, even for a closed home market.",
    )
    parser.add_argument(
        "--no-logo-check",
        action="store_true",
        help="Skip the logo change check. A new logo still downloads.",
    )
    parser.add_argument(
        "--no-universe-fetch",
        action="store_true",
        help=(
            "Skip the ticker universe refresh. The sectors then come from the "
            "universe file of the previous run."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be 1 or more")
    if args.min_interval < 0:
        parser.error("--min-interval must be 0 or more")

    try:
        return run(args)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
