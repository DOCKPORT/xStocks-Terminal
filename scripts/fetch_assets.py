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

The quote endpoint has no bulk variant. One call covers one symbol, so 723
calls per run. While the market is closed the server waits about 21 seconds on
a price lookup, then returns null. During trading hours the lookup should
answer in seconds. The exact in-market latency is not measured yet.

The script therefore only fetches quotes during US trading hours
(pre-market and after-hours included: 4:00 to 20:00 ET, Monday to Friday,
market holidays excluded). While the market is closed it skips every quote
call and keeps the last known price from the previous run.

Output: data/xstocks-assets.json
  array of { name, symbol, sharesHeld, circulatingSupply, price, priceUpdatedAt }

The page reads that file with fetch, so the script writes no second file.

A new symbol in the catalog has no logo yet, so the script runs
scripts/fetch_logos.py after the write. The logo script skips every saved
file, so only the new logos download. A dropped symbol keeps its logo file.

That logo script also compares every saved logo with the server. An image that
changed on the server replaces the saved file, and the run prints each change.
Pass --no-logo-check to skip the compare and the extra requests.

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
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

API_BASE = "https://api.backed.fi/api/v2/public"
ASSETS_URL = f"{API_BASE}/assets"
RESERVES_URL = f"{API_BASE}/proof-of-reserves"

# The API rejects the default urllib User-Agent with HTTP 403.
USER_AGENT = "xstocks-terminal/1.0"

REQUEST_TIMEOUT_SECONDS = 60
REQUEST_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 2
DEFAULT_WORKERS = 32

MARKET_ZONE = ZoneInfo("America/New_York")
PREMARKET_OPEN = clock_time(4, 0)
AFTERHOURS_CLOSE = clock_time(20, 0)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
LOGO_SCRIPT = REPO_ROOT / "scripts" / "fetch_logos.py"

Price = int | float | None
Record = dict[str, Any]


def fetch_json(url: str, attempts: int = REQUEST_ATTEMPTS) -> Any:
    """Fetch one URL and decode the JSON body. Retry a transport error."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                payload = response.read()
            return json.loads(payload)
        except (OSError, ValueError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"request failed: {url}: {last_error}")


def fetch_pages(url: str, label: str) -> list[Record]:
    """Walk every page of a paginated endpoint and return the nodes."""
    records: list[Record] = []
    page = 1
    while True:
        body = fetch_json(f"{url}?page={page}")
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


def merge_records(
    asset_nodes: list[Record], reserve_nodes: list[Record]
) -> tuple[list[Record], list[str]]:
    """Join the reserves onto the catalog by symbol.

    Return the kept records and the symbols dropped for zero shares held.
    """
    reserves: dict[str, tuple[Any, Any]] = {}
    for node in reserve_nodes:
        symbol = node.get("symbol")
        if isinstance(symbol, str):
            reserves[symbol] = (node.get("sharesHeld"), node.get("circulatingSupply"))

    merged: list[Record] = []
    dropped: list[str] = []
    for node in asset_nodes:
        symbol = node.get("symbol")
        name = node.get("name")
        if not isinstance(symbol, str) or not isinstance(name, str):
            continue

        shares, supply = reserves.get(symbol, (None, None))
        if shares == "0":
            dropped.append(symbol)
            continue

        merged.append(
            {
                "name": name,
                "symbol": symbol,
                "sharesHeld": shares,
                "circulatingSupply": supply,
            }
        )
    return merged, dropped


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    """Return the nth given weekday of a month. Monday is 0."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last given weekday of a month. Monday is 0."""
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed(day: date) -> date:
    """Shift a fixed holiday off the weekend, as the exchange does."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter_sunday(year: int) -> date:
    """Return Easter Sunday. Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    leap = (32 + 2 * e + 2 * i - h - k) % 7
    correction = (a + 11 * h + 22 * leap) // 451
    month = (h + leap - 7 * correction + 114) // 31
    day = ((h + leap - 7 * correction + 114) % 31) + 1
    return date(year, month, day)


def us_market_holidays(year: int) -> set[date]:
    """Return the ten US market holidays for one year."""
    return {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }


def market_is_open(moment: datetime) -> bool:
    """True during US pre-market, regular, or after-hours trading."""
    local = moment.astimezone(MARKET_ZONE)
    if local.weekday() >= 5:
        return False

    # The next year is included: an observed New Year's Day can fall in December.
    holidays = us_market_holidays(local.year) | us_market_holidays(local.year + 1)
    if local.date() in holidays:
        return False

    return PREMARKET_OPEN <= local.time() < AFTERHOURS_CLOSE


def load_last_known(path: Path) -> dict[str, Record]:
    """Read the prices from the previous run. This holds the last known value."""
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
            }
    return known


def fetch_quote(symbol: str) -> Price:
    """Fetch one quote. Return None on a null quote, a timeout, or an error."""
    url = f"{ASSETS_URL}/{symbol}/price-data"
    try:
        body = fetch_json(url)
    except RuntimeError as error:
        print(f"Warning: quote failed for {symbol}: {error}", file=sys.stderr)
        return None

    quote = body.get("quote") if isinstance(body, dict) else None
    if isinstance(quote, bool) or not isinstance(quote, (int, float)):
        return None
    return quote


def _is_price(value: Any) -> bool:
    """True for a real number. A bool is not a price."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def apply_prices(
    records: list[Record], quotes: list[Price], last_known: dict[str, Record]
) -> tuple[int, int, int]:
    """Write the price. A null quote keeps the last known value. Return counts."""
    fresh = 0
    retained = 0
    unavailable = 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for record, quote in zip(records, quotes):
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


def run(args: argparse.Namespace) -> int:
    """Fetch everything, merge it, and write the JSON snapshot."""
    # Read the symbol set before the write, so the compare has a baseline.
    has_baseline = OUT_JSON.is_file()
    last_known = load_last_known(OUT_JSON)

    print("Fetching assets...")
    asset_nodes = fetch_pages(ASSETS_URL, "assets")

    print("Fetching proof of reserves...")
    reserve_nodes = fetch_pages(RESERVES_URL, "reserves")

    records, dropped_symbols = merge_records(asset_nodes, reserve_nodes)
    fetched_total = len(asset_nodes)
    dropped = len(dropped_symbols)

    moment = datetime.now(timezone.utc)
    trading = market_is_open(moment)
    stamp = moment.astimezone(MARKET_ZONE).strftime("%Y-%m-%d %H:%M %Z")

    quotes: list[Price]
    if trading or args.force_quotes:
        state = "open" if trading else "closed, forced"
        print(
            f"Market is {state} at {stamp}. Fetching {len(records)} quotes "
            f"with {args.workers} workers..."
        )
        symbols = [record["symbol"] for record in records]
        quotes = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for quote in pool.map(fetch_quote, symbols):
                quotes.append(quote)
                done = len(quotes)
                if done % 100 == 0 or done == len(symbols):
                    print(f"  quotes: {done}/{len(symbols)}")
    else:
        print(f"Market is closed at {stamp}. Skipped {len(records)} quote calls.")
        quotes = [None] * len(records)

    fresh, retained, unavailable = apply_prices(records, quotes, last_known)

    write_outputs(records)

    new_symbols = report_symbol_changes(records, last_known, has_baseline)

    with_reserves = sum(
        1 for record in records if record["circulatingSupply"] is not None
    )
    no_reserve = ", ".join(
        record["symbol"]
        for record in records
        if record["circulatingSupply"] is None
    )

    print(f"Wrote {len(records)} assets ({with_reserves} with reserves) to {OUT_JSON}")
    print(f"Filtered out {dropped} assets with zero shares held (fetched {fetched_total})")
    if dropped_symbols:
        print(f"Zero shares held: {', '.join(dropped_symbols)}")
    print(f"Prices: {fresh} fresh, {retained} retained, {unavailable} unavailable")
    if no_reserve:
        print(f"Assets with no reserve entry: {no_reserve}")

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
        "--force-quotes",
        action="store_true",
        help="Fetch quotes even when the US market is closed.",
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

    try:
        return run(args)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
