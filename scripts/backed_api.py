#!/usr/bin/env python3
"""
The xStocks API client for the scripts in this folder.

This module holds every part that knows the public API at api.backed.fi: the
endpoint paths, the page walker, the catalog field readers, the market flag,
the single value fetch, and the pooled bulk fetch.

The API answers two lists and two numbers:
  1. /public/assets                     - the catalog: name, symbol, trading flag
  2. /public/proof-of-reserves          - sharesHeld and circulatingSupply
  3. /public/assets/{symbol}/price-data - the quote, one call per symbol
  4. /public/assets/{symbol}/multiplier - the multiplier, one call per symbol

Both list endpoints paginate with 100 items per page and a hasNextPage flag.
The proof-of-reserves totalNodes value is wrong, so the walker uses the flag,
not the total. The quote calls share one pacer, and scripts/http_client.py
holds that layer.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  import backed_api
  nodes = backed_api.fetch_pages(backed_api.ASSETS_URL, "assets")
"""  # noqa: EXE001

from __future__ import annotations

import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

import http_client

API_BASE = "https://api.backed.fi/api/v2/public"
ASSETS_URL = f"{API_BASE}/assets"
RESERVES_URL = f"{API_BASE}/proof-of-reserves"

# The catalog marks every asset name with this text, for example
# "Tesla xStock". The symbol carries the same mark, so the snapshot drops the
# words and the page keeps the name column narrow.
NAME_SUFFIX = " xStock"

# The log lines print in Eastern time, where the main session runs.
MARKET_ZONE = ZoneInfo("America/New_York")

# The progress lines print one line per this many calls.
PROGRESS_EVERY = 100

# A page of the catalog or of the reserves gets two attempts on a transport
# error. The quote calls use the count below.
PAGE_ATTEMPTS = 2

# The price endpoint rate limits a burst of quote calls. Pace those calls only.
QUOTE_ATTEMPTS = 4

# The multiplier endpoint needs a network name. It answers the same value on
# every network, so one name serves the whole run.
MULTIPLIER_NETWORK = "Solana"
MULTIPLIER_ATTEMPTS = 3

# One fetched number. A failed call reads None, so the caller keeps the value
# of the previous run.
Value = int | float | None

Record = dict[str, Any]

# One fetched value and the rate-limit flag of the call.
FetchResult = tuple[Value, bool]


def is_number(value: Any) -> bool:
    """True for a real number. A bool is not a number."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fetch_pages(url: str, label: str) -> list[Record]:
    """Walk every page of a paginated endpoint and return the nodes.

    Follow the hasNextPage flag, because the reserve totalNodes value is wrong.
    A nodes value that is not a list stops the run, so a bad answer never looks
    like an empty page.
    """
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


def _fetch_value(
    url: str,
    kind: str,
    field: str,
    attempts: int,
    symbol: str,
    pacer: http_client.Pacer,
) -> FetchResult:
    """Fetch one number field. Return the value and a rate-limit flag.

    A rate-limit status raises RateLimitError, and the flag then reads True. A
    plain error prints a warning, and the value reads None. The call takes its
    own time slot from the pacer, and the HTTP layer waits for the Retry-After
    value. A missing field, a null, or a text value reads None. The kind names
    the endpoint in the message, and the symbol names the item.
    """
    try:
        body = http_client.fetch_json(url, attempts, pacer=pacer)
    except http_client.RateLimitError as error:
        print(f"Warning: {kind} rate limited for {symbol}: {error}", file=sys.stderr)
        return None, True
    except RuntimeError as error:
        print(f"Warning: {kind} failed for {symbol}: {error}", file=sys.stderr)
        return None, False

    value = body.get(field) if isinstance(body, dict) else None
    if not is_number(value):
        return None, False
    return value, False


def fetch_quote(symbol: str, pacer: http_client.Pacer) -> FetchResult:
    """Fetch the price of one symbol. Return the value and a rate-limit flag."""
    url = f"{ASSETS_URL}/{symbol}/price-data"
    return _fetch_value(url, "quote", "quote", QUOTE_ATTEMPTS, symbol, pacer)


def _fetch_many(
    todo: list[str],
    fetch_one: Callable[[str], FetchResult],
    workers: int,
    label: str,
) -> tuple[list[Value], int]:
    """Fetch one value per item with a thread pool. Return the values and a count.

    The values arrive in item order. The progress line prints after each
    PROGRESS_EVERY calls, and after the final call. The count holds the
    rate-limited calls. The caller sets the pacing on the passed callable.
    """
    fetched: list[Value] = []
    rate_limited = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for value, limited in pool.map(fetch_one, todo):
            fetched.append(value)
            if limited:
                rate_limited += 1
            done = len(fetched)
            if done % PROGRESS_EVERY == 0 or done == len(todo):
                print(f"  {label}: {done}/{len(todo)}")

    return fetched, rate_limited


def fetch_quotes(
    symbols: list[str],
    closed: set[str],
    *,
    workers: int,
    interval: float,
) -> tuple[list[Value], int]:
    """Fetch one quote per open-market symbol.

    Return the price list, in symbol order, and the count of rate-limited
    calls. A skipped symbol reads None, so it keeps the last known price.
    With no open market the list holds one None per symbol, so the last known
    price still stands on every row.

    The closed set names the symbols whose home market has no session. Each
    call takes one time slot from the pacer, and the interval sets the gap.
    """
    todo = [symbol for symbol in symbols if symbol not in closed]
    skipped = len(symbols) - len(todo)
    stamp = (
        datetime.now(timezone.utc).astimezone(MARKET_ZONE).strftime("%Y-%m-%d %H:%M %Z")
    )

    print(f"Fetching {len(todo)} quotes at {stamp} with {workers} workers...")
    if skipped:
        print(f"  Skipped {skipped}: the home market is closed.")
    if not todo:
        print("  No market is open now, so every quote call is skipped.")
        return [None] * len(symbols), 0

    pacer = http_client.Pacer(interval)
    fetched, rate_limited = _fetch_many(
        todo, partial(fetch_quote, pacer=pacer), workers, "quotes"
    )
    price_by_symbol = dict(zip(todo, fetched))
    return [price_by_symbol.get(symbol) for symbol in symbols], rate_limited


def fetch_multiplier(symbol: str, pacer: http_client.Pacer) -> FetchResult:
    """Fetch the multiplier of one symbol.

    The endpoint needs a network name, and it answers the same value on every
    network. Return the value and a rate-limit flag.
    """
    url = f"{ASSETS_URL}/{symbol}/multiplier?network={MULTIPLIER_NETWORK}"
    return _fetch_value(
        url, "multiplier", "currentMultiplier", MULTIPLIER_ATTEMPTS, symbol, pacer
    )


def fetch_multipliers(
    symbols: list[str], *, workers: int, interval: float
) -> list[Value]:
    """Fetch one multiplier per symbol.

    Every symbol takes a call, because this endpoint has no market gate. Return
    the values in symbol order. The interval sets the gap between the calls.
    """
    print(f"Fetching {len(symbols)} multipliers with {workers} workers...")

    pacer = http_client.Pacer(interval)
    fetched, rate_limited = _fetch_many(
        symbols, partial(fetch_multiplier, pacer=pacer), workers, "multipliers"
    )
    if rate_limited:
        print(f"  Rate limited: {rate_limited}")

    return fetched
