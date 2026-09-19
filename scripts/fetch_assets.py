#!/usr/bin/env python3
"""
Download every xStock asset, its proof of reserves, and its price quote, then
store one merged JSON file.

Three public endpoints are used:
  1. /public/assets                     - catalog: name, symbol, logo, chains
  2. /public/proof-of-reserves          - sharesHeld and circulatingSupply
  3. /public/assets/{symbol}/price-data - the current quote, one symbol per call

Both list endpoints paginate with 100 items per page and a hasNextPage flag.
The proof-of-reserves totalNodes value is wrong (830), so the loop uses the
flag, not the total.

The script fetches a quote for every asset whose home market is open. Each
catalog row carries a trading block. A false openNow value means the home
exchange has no session, and the price endpoint then waits about 21 seconds and
answers null. The script skips those symbols, so they keep the last known price.
A missing flag fetches the quote, and --force-quotes calls every symbol anyway.

Output: data/xstocks-assets.json
  array of { name, symbol, listingCountry, sector, industry, exchange,
            sharesHeld, circulatingSupply, price, priceUpdatedAt }
  one row per asset that holds a reserve row with a live balance

The name field holds no " xStock" mark. The catalog adds that mark to every
name, so the script drops it and the page shows the plain name, for example
"Tesla" in place of "Tesla xStock".

listingCountry is the country code of the venue that lists the underlying share,
for example "HK" for Bank Of China xStock. The catalog row carries that value in
its underlying object, so the field costs no extra request.

circulatingSupply is the token supply that the public holds, not the minted
supply. See memory-bank/notes.md for the full meaning. The script drops a row
when sharesHeld is "0" or when circulatingSupply is "0". A zero in either field
means that no live reserve exists.

The sector, the industry, and the exchange come from data/ticker_universe.json,
which scripts/ticker_universe.py writes. scripts/sector_map.py holds the match
rules and backfills a file without a fetch. Without a universe file, each asset
keeps the sector, the industry, and the exchange of the last run. A value that
the universe misses reads null, and the page then leaves that label out.

The quote calls share one pacer. Each call takes one time slot. The default
gap is 0.25 seconds. Pass --min-interval to change the gap. A 429 or 503
answer waits for the Retry-After header, then backs off.

The page reads that file with fetch, so the script writes no second file.

A new symbol in the catalog has no logo yet, so the script runs
scripts/fetch_logos.py after the write. The logo script skips every saved
file, so only the new logos download. A dropped symbol keeps its logo file.

That logo script also compares every saved logo with the server. An image that
changed on the server replaces the saved file, and the run prints each change.
Pass --no-logo-check to skip the compare and the extra requests.

scripts/http_client.py holds the shared HTTP layer: the User-Agent, the
timeout, the retry count, the rate-limit wait, and the call pacer.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/fetch_assets.py
  ./scripts/fetch_assets.py --workers 64
  ./scripts/fetch_assets.py --force-quotes
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import http_client
import sector_map

API_BASE = "https://api.backed.fi/api/v2/public"
ASSETS_URL = f"{API_BASE}/assets"
RESERVES_URL = f"{API_BASE}/proof-of-reserves"

# The catalog marks every asset name with this text, for example
# "Tesla xStock". The symbol carries the same mark, so the snapshot drops the
# words and the page keeps the name column narrow.
NAME_SUFFIX = " xStock"

# The log lines print in Eastern time, where the main session runs.
MARKET_ZONE = ZoneInfo("America/New_York")

DEFAULT_WORKERS = 8

# A page of the catalog or of the reserves gets two attempts on a transport
# error. The quote calls use the count below.
PAGE_ATTEMPTS = 2

# The price endpoint rate limits a burst of quote calls. Pace those calls only.
QUOTE_ATTEMPTS = 4
QUOTE_INTERVAL_SECONDS = 0.25

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
LOGO_SCRIPT = REPO_ROOT / "scripts" / "fetch_logos.py"

Price = int | float | None
Record = dict[str, Any]
QuoteResult = tuple[Price, bool]


def fetch_pages(url: str, label: str) -> list[Record]:
    """Walk every page of a paginated endpoint and return the nodes."""
    records: list[Record] = []
    page = 1
    while True:
        body = http_client.fetch_json(f"{url}?page={page}", PAGE_ATTEMPTS)
        nodes = body.get("nodes") if isinstance(body, dict) else None
        if not isinstance(nodes, list):
            raise RuntimeError(f"{label} page {page} did not return a valid list.")  # noqa: TRY004
        if not nodes:
            break

        records.extend(node for node in nodes if isinstance(node, dict))

        page_meta = body.get("page")
        has_next = (
            bool(page_meta.get("hasNextPage")) if isinstance(page_meta, dict) else False
        )
        print(
            f"  {label} page {page}: {len(nodes)} items "
            f"(hasNextPage={str(has_next).lower()})"
        )
        if not has_next:
            break
        page += 1
    return records


def listing_country(node: Record) -> str | None:
    """Return the country that lists the underlying share, or None.

    The catalog holds the value in the underlying object of the same row, so no
    extra request is needed. A missing object, a missing field, or an empty
    string returns None.
    """
    underlying = node.get("underlying")
    if not isinstance(underlying, dict):
        return None

    country = underlying.get("listingCountry")
    if isinstance(country, str):
        return country.strip() or None
    return None


def short_name(name: str) -> str:
    """Return the asset name without the trailing xStock mark.

    The catalog marks every name with " xStock", for example "Tesla xStock".
    The symbol already carries that mark, so the snapshot drops the words and
    the page shows "Tesla". The compare ignores case and the space around the
    name. A name that holds the mark alone stays unchanged.
    """
    trimmed = name.strip()
    if not trimmed.lower().endswith(NAME_SUFFIX.lower()):
        return name

    short = trimmed[: -len(NAME_SUFFIX)].strip()
    return short or name


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
        name = short_name(name)

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
                "listingCountry": listing_country(node),
                "sector": None,
                "industry": None,
                "exchange": None,
                "sharesHeld": shares,
                "circulatingSupply": supply,
            }
        )
    return merged, dropped, thin_supply, absent


def closed_market_symbols(asset_nodes: list[Record]) -> set[str]:
    """Return the symbols whose home market is closed, from the trading flag.

    A false openNow value means the home exchange has no session. The price
    endpoint then waits about 21 seconds and answers null, so the caller skips
    those symbols. A missing flag returns no symbol, so that asset keeps its
    quote call.
    """
    closed: set[str] = set()
    for node in asset_nodes:
        symbol = node.get("symbol")
        trading = node.get("trading")
        if not isinstance(symbol, str) or not isinstance(trading, dict):
            continue
        if trading.get("openNow") is False:
            closed.add(symbol)
    return closed


def load_last_known(path: Path) -> dict[str, Record]:
    """Read the values of the previous run. This holds the last known value.

    The prices and the sectors both come from here. The previous sector stands
    when the ticker universe file is absent.
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
                "sector": row.get("sector"),
            }
    return known


def fetch_quote(symbol: str, pacer: http_client.Pacer) -> QuoteResult:
    """Fetch one quote. Return the price and a rate-limit flag.

    A null quote, a timeout, or a plain error returns the price None. The
    quote call takes its own time slot from the pacer, and a rate-limit status
    waits for the Retry-After value.
    """
    url = f"{ASSETS_URL}/{symbol}/price-data"
    try:
        body = http_client.fetch_json(
            url, QUOTE_ATTEMPTS, pacer=pacer
        )
    except http_client.RateLimitError as error:
        print(f"Warning: quote rate limited for {symbol}: {error}", file=sys.stderr)
        return None, True
    except RuntimeError as error:
        print(f"Warning: quote failed for {symbol}: {error}", file=sys.stderr)
        return None, False

    quote = body.get("quote") if isinstance(body, dict) else None
    if isinstance(quote, bool) or not isinstance(quote, (int, float)):
        return None, False
    return quote, False


def _is_price(value: Any) -> bool:
    """True for a real number. A bool is not a price."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def apply_prices(
    records: list[Record], quotes: list[Price], last_known: dict[str, Record]
) -> tuple[int, int, int]:
    """Write the price. A null quote keeps the last known value. Return counts.

    The record holds the symbol order, and the quote list matches that order.
    A short quote list reads None for the missing tail, so the last known price
    stands. The zip call cannot do this job, because it drops the tail rows.
    """
    fresh = 0
    retained = 0
    unavailable = 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for index, record in enumerate(records):
        quote = quotes[index] if index < len(quotes) else None
        if quote is not None:
            record["price"] = quote
            record["priceUpdatedAt"] = stamp
            fresh += 1
            continue

        previous = last_known.get(record["symbol"], {})
        previous_price = previous.get("price")
        if _is_price(previous_price):
            record["price"] = previous_price
            record["priceUpdatedAt"] = previous.get("priceUpdatedAt")
            retained += 1
        else:
            record["price"] = None
            record["priceUpdatedAt"] = None
            unavailable += 1

    return fresh, retained, unavailable


def write_outputs(records: list[Record]) -> None:
    """Write the JSON snapshot that the page reads."""
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records, indent=2, ensure_ascii=False)
    OUT_JSON.write_text(payload + "\n", encoding="utf-8")


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


def refresh_logos(new_symbols: list[str], check_changes: bool) -> None:
    """Run the logo script for the new symbols and the changed logos.

    Warn on a child failure. The asset snapshot is still valid, so the caller
    keeps its own exit code.
    """
    if not new_symbols and not check_changes:
        return

    command = [sys.executable, str(LOGO_SCRIPT)]
    if check_changes:
        print("Checking the saved logos with the server...")
        command.append("--check-changes")

    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        print(
            "Warning: the logo download failed. "
            "Run scripts/fetch_logos.py to retry.",
            file=sys.stderr,
        )


def fetch_all_quotes(
    symbols: list[str], closed: set[str], args: argparse.Namespace
) -> tuple[list[Price], int]:
    """Fetch one quote per open-market symbol.

    Return the price list, in symbol order, and the count of rate-limited
    calls. A skipped symbol reads None, so it keeps the last known price.
    With no open market the list holds one None per symbol, so the last known
    price still stands on every row.
    """
    todo = [symbol for symbol in symbols if symbol not in closed]
    skipped = len(symbols) - len(todo)
    stamp = (
        datetime.now(timezone.utc).astimezone(MARKET_ZONE).strftime("%Y-%m-%d %H:%M %Z")
    )

    print(f"Fetching {len(todo)} quotes at {stamp} with {args.workers} workers...")
    if skipped:
        print(f"  Skipped {skipped}: the home market is closed.")
    if not todo:
        print("  No market is open now, so every quote call is skipped.")
        return [None] * len(symbols), 0

    pacer = http_client.Pacer(args.min_interval)
    paced = partial(fetch_quote, pacer=pacer)
    rate_limited = 0
    fetched: list[Price] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for price, limited in pool.map(paced, todo):
            fetched.append(price)
            if limited:
                rate_limited += 1
            done = len(fetched)
            if done % 100 == 0 or done == len(todo):
                print(f"  quotes: {done}/{len(todo)}")

    price_by_symbol = dict(zip(todo, fetched))
    return [price_by_symbol.get(symbol) for symbol in symbols], rate_limited


def report_filters(
    dropped: list[str], thin_supply: list[str], absent: list[str], fetched_total: int
) -> None:
    """Print the rows that the reserve filter removed, and the reason."""
    removed = len(dropped) + len(thin_supply) + len(absent)
    print(
        f"Filtered out {removed} assets (fetched {fetched_total}): "
        f"{len(dropped)} zero shares held, "
        f"{len(thin_supply)} zero circulating supply, "
        f"{len(absent)} no reserve entry"
    )
    if dropped:
        print(f"Zero shares held: {', '.join(dropped)}")
    if thin_supply:
        print(f"Zero circulating supply: {', '.join(thin_supply)}")
    if absent:
        print(f"No reserve entry: {', '.join(absent)}")


def run(args: argparse.Namespace) -> int:
    """Fetch everything, merge it, and write the JSON snapshot."""
    # Read the symbol set before the write, so the compare has a baseline.
    has_baseline = OUT_JSON.is_file()
    last_known = load_last_known(OUT_JSON)

    print("Fetching assets...")
    asset_nodes = fetch_pages(ASSETS_URL, "assets")

    print("Fetching proof of reserves...")
    reserve_nodes = fetch_pages(RESERVES_URL, "reserves")

    records, dropped, thin_supply, absent = merge_records(asset_nodes, reserve_nodes)
    symbols = [record["symbol"] for record in records]

    closed = set() if args.force_quotes else closed_market_symbols(asset_nodes)
    quotes, rate_limited = fetch_all_quotes(symbols, closed, args)

    fresh, retained, unavailable = apply_prices(records, quotes, last_known)

    # A missing or broken universe file keeps the sector of the previous run.
    sector_counts = sector_map.apply_sectors(
        records, sector_map.load_index(), last_known
    )

    write_outputs(records)
    new_symbols = report_symbol_changes(records, last_known, has_baseline)

    print(f"Wrote {len(records)} assets to {OUT_JSON}")
    report_filters(dropped, thin_supply, absent, len(asset_nodes))
    print(f"Prices: {fresh} fresh, {retained} retained, {unavailable} unavailable")
    print(f"Rate limited quotes: {rate_limited}")
    print(sector_map.counts_line(sector_counts))
    print(country_counts_line(records))

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
