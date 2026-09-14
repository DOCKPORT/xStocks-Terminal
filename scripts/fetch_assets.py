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
  array of { name, symbol, sharesHeld, circulatingSupply, price, priceUpdatedAt }

circulatingSupply is the token supply that the public holds, not the minted
supply. See memory-bank/notes.md for the full meaning.

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
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

API_BASE = "https://api.backed.fi/api/v2/public"
ASSETS_URL = f"{API_BASE}/assets"
RESERVES_URL = f"{API_BASE}/proof-of-reserves"

# The API rejects the default urllib User-Agent with HTTP 403.
USER_AGENT = "xstocks-terminal/1.0"

# The log lines print in Eastern time, where the main session runs.
MARKET_ZONE = ZoneInfo("America/New_York")

REQUEST_TIMEOUT_SECONDS = 60
REQUEST_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 2
DEFAULT_WORKERS = 8

# The price endpoint rate limits a burst of quote calls. Pace those calls only.
QUOTE_ATTEMPTS = 4
QUOTE_INTERVAL_SECONDS = 0.25
RATE_LIMIT_CODES = (429, 503)
RATE_LIMIT_BACKOFF_SECONDS = (2.0, 4.0, 8.0)
RATE_LIMIT_MAX_WAIT_SECONDS = 30.0

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
LOGO_SCRIPT = REPO_ROOT / "scripts" / "fetch_logos.py"

Price = int | float | None
Record = dict[str, Any]
QuoteResult = tuple[Price, bool]

# One time slot per quote call, shared by every worker thread.
_PACER_LOCK = threading.Lock()
_PACER_NEXT_SLOT = 0.0


class RateLimitError(RuntimeError):
    """The server refused the request with a rate-limit status."""


def _wait_for_slot(interval: float) -> None:
    """Hold the caller until its time slot. One slot per interval, all threads."""
    global _PACER_NEXT_SLOT
    with _PACER_LOCK:
        start = max(time.monotonic(), _PACER_NEXT_SLOT)
        _PACER_NEXT_SLOT = start + interval
    delay = start - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def _retry_after_seconds(error: urllib.error.HTTPError) -> float | None:
    """Read the Retry-After header. Return the wait in seconds, or None.

    The value is a number of seconds or an HTTP date.
    """
    header = error.headers.get("Retry-After") if error.headers else None
    if not header:
        return None

    seconds: float | None
    try:
        seconds = float(header)
    except ValueError:
        seconds = None
    if seconds is not None:
        return max(0.0, seconds)

    try:
        moment = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())


def _rate_limit_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    """Return the wait before a retry. Honor Retry-After, then back off."""
    header_seconds = _retry_after_seconds(error)
    if header_seconds is not None:
        return min(header_seconds, RATE_LIMIT_MAX_WAIT_SECONDS)

    index = min(attempt - 1, len(RATE_LIMIT_BACKOFF_SECONDS) - 1)
    return RATE_LIMIT_BACKOFF_SECONDS[index]


def fetch_json(
    url: str,
    attempts: int = REQUEST_ATTEMPTS,
    *,
    pace_seconds: float = 0.0,
    respect_retry_after: bool = False,
) -> Any:
    """Fetch one URL and decode the JSON body. Retry a transport error.

    A positive pace_seconds holds the call until its time slot. With
    respect_retry_after set, a rate-limit status waits for the Retry-After
    value. Both options serve the quote calls only.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last_error: Exception | None = None
    rate_limited = False
    for attempt in range(1, attempts + 1):
        if pace_seconds > 0:
            _wait_for_slot(pace_seconds)
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                payload = response.read()
            return json.loads(payload)
        except urllib.error.HTTPError as error:
            last_error = error
            if respect_retry_after and error.code in RATE_LIMIT_CODES:
                rate_limited = True
                if attempt < attempts:
                    time.sleep(_rate_limit_delay(error, attempt))
                continue
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SECONDS)
        except (OSError, ValueError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SECONDS)

    if rate_limited:
        raise RateLimitError(f"rate limited: {url}: {last_error}")
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


def fetch_quote(
    symbol: str, pace_seconds: float = QUOTE_INTERVAL_SECONDS
) -> QuoteResult:
    """Fetch one quote. Return the price and a rate-limit flag.

    A null quote, a timeout, or a plain error returns the price None. The
    quote call gets its own time slot, and a rate-limit status waits for the
    Retry-After value.
    """
    url = f"{ASSETS_URL}/{symbol}/price-data"
    try:
        body = fetch_json(
            url,
            QUOTE_ATTEMPTS,
            pace_seconds=pace_seconds,
            respect_retry_after=True,
        )
    except RateLimitError as error:
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
    stamp = moment.astimezone(MARKET_ZONE).strftime("%Y-%m-%d %H:%M %Z")

    symbols = [record["symbol"] for record in records]
    closed = set() if args.force_quotes else closed_market_symbols(asset_nodes)
    todo = [symbol for symbol in symbols if symbol not in closed]
    skipped = len(symbols) - len(todo)

    print(
        f"Fetching {len(todo)} quotes at {stamp} "
        f"with {args.workers} workers..."
    )
    if skipped:
        print(f"  Skipped {skipped}: the home market is closed.")
    if not todo:
        print("  No market is open now, so every quote call is skipped.")

    rate_limited = 0
    fetched: list[Price] = []
    paced = partial(fetch_quote, pace_seconds=args.min_interval)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for price, limited in pool.map(paced, todo):
            fetched.append(price)
            if limited:
                rate_limited += 1
            done = len(fetched)
            if done % 100 == 0 or done == len(todo):
                print(f"  quotes: {done}/{len(todo)}")
    price_by_symbol = dict(zip(todo, fetched))
    quotes = [price_by_symbol.get(symbol) for symbol in symbols]

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
    print(f"Rate limited quotes: {rate_limited}")
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
