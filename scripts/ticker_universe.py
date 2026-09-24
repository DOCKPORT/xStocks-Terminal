#!/usr/bin/env python3
"""
Fetch the listed ticker universe from BusinessQuant and store one JSON file.

One endpoint is used:
  https://data.businessquant.com/universe?api_key=KEY

The key arrives in one of three places, in this order:
  1. The BUSINESSQUANT_API_KEY environment variable.
  2. The text file that --api-key-file names.
  3. The local file scripts/bq_key.py, which .gitignore holds.

The local key file starts with an empty value. Put your key there. The script
holds no key of its own. Every printed line passes redact(), because the
request URL carries the key. The script prints the source name, never the key.

A 401 or 403 answer stops the run at once, with one clear line. A 429 or 503
answer waits for the Retry-After header, then backs off. A transport error
retries. scripts/http_client.py holds that shared HTTP layer.

The script keeps only the rows that our symbols need. data/xstocks-assets.json
holds those symbols, and the base symbol is the asset symbol minus the final
"x". A base symbol with a dot also fits the dash form, and the other way
around, because the universe spells a share class either way. "BRK.Bx" then
fits "BRK-B".

The run prints the base symbols that no row answers. A missing asset snapshot
stops the run, because the filter would then hold no symbol list.

One ticker can hold rows of more than one security type, because two issuers can
use the same ticker. The match rules of scripts/sector_map.py take the type that
comes first, so a row of a lower type can never decide a value. The script drops
those rows. The ticker META holds an Equity row for Meta Platforms and a Fund row
for a fund series, and the Fund row drops.

Output: data/ticker_universe.json
  {
    "source": "https://data.businessquant.com/universe",
    "fetchedAt": "2026-09-15T18:18:50+00:00",
    "universeCount": 45400,
    "count": 647,
    "tickers": [ ... one row per kept ticker, exactly as the API returned it ... ]
  }

The rows stay untouched, so a later script reads the true field names. The run
prints those field names. universeCount is the size of the fetched payload, and
count is the number of kept rows.

The write is skipped when the payload holds no rows, or when the fetched row
count falls below MIN_KEEP_RATIO of the previous run. A cut payload then keeps
the good file. Pass --force to write anyway. Pass --dry-run to write nothing.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  Put your key in scripts/bq_key.py, then run:
    ./scripts/ticker_universe.py

  Or name the key in the environment:
    BUSINESSQUANT_API_KEY=... ./scripts/ticker_universe.py

  Or name a key file:
    ./scripts/ticker_universe.py --api-key-file ~/.bq-key
"""  # noqa: EXE001

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import http_client

UNIVERSE_URL = "https://data.businessquant.com/universe"
API_KEY_ENV = "BUSINESSQUANT_API_KEY"

# The rows sit in the payload itself, or under one of these keys.
ROW_KEYS = ("tickers", "data", "results", "universe", "nodes", "items")

# A run below this share of the last run stops, so a cut payload cannot
# replace a good file.
MIN_KEEP_RATIO = 0.8

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent

# The local key file. Put your key there, and .gitignore keeps it out of git.
KEY_MODULE = SCRIPTS_DIR / "bq_key.py"

# The asset snapshot. The filter reads the symbols that our page shows.
ASSETS_JSON = REPO_ROOT / "data" / "xstocks-assets.json"

OUT_JSON = REPO_ROOT / "data" / "ticker_universe.json"

# The type order of scripts/sector_map.py. A row of a lower type can never win,
# so the filter drops it.
TYPE_ORDER = ("Equity", "ETF", "Fund", "Index")

Row = dict[str, Any]


def redact(text: str, key: str = "") -> str:
    """Hide the API key in a message. The key sits in the request URL."""
    if key:
        text = text.replace(key, "***")
    return re.sub(r"(api_key=)[^&\s]+", r"\1***", text)


def read_key_file(path: Path) -> str:
    """Read the key from a text file.

    The file holds the bare key, or one KEY=value line. Comments and empty
    lines are ignored.
    """
    if not path.is_file():
        raise RuntimeError(f"no API key file at {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            line = line.split("=", 1)[1]
        value = line.strip().strip("'\"")
        if value:
            return value

    raise RuntimeError(f"the API key file {path} holds no key")


def read_key_module(path: Path) -> str | None:
    """Read the key from the local key file. Return None when it holds no key.

    The file holds one assignment: BUSINESSQUANT_API_KEY = "your key".
    """
    if not path.is_file():
        return None

    spec = importlib.util.spec_from_file_location("bq_key", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the local key file {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    value = getattr(module, API_KEY_ENV, "")
    if not isinstance(value, str):
        raise RuntimeError(  # noqa: TRY004
            f"the local key file {path} must hold text in {API_KEY_ENV}"
        )
    return value.strip() or None


def read_api_key(path: Path | None) -> tuple[str, str]:
    """Return the API key and the name of the source.

    The order is: the environment variable, then the file that
    --api-key-file names, then the local key file.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key, f"the {API_KEY_ENV} environment variable"

    if path is not None:
        return read_key_file(path), f"the file {path}"

    module_key = read_key_module(KEY_MODULE)
    if module_key:
        return module_key, f"the local key file {KEY_MODULE.relative_to(REPO_ROOT)}"

    raise RuntimeError(
        f"no API key. Set {API_KEY_ENV}, name a file with --api-key-file, "
        f"or put the key in {KEY_MODULE.relative_to(REPO_ROOT)}."
    )


def universe_rows(payload: Any) -> list[Row]:
    """Return the ticker rows from the payload.

    The payload is a list of rows, or a wrapper that holds the list under a
    known key. A wrapper without a known key uses its first list value.
    """
    if isinstance(payload, list):
        rows: Any = payload
    elif isinstance(payload, dict):
        rows = None
        for name in ROW_KEYS:
            if isinstance(payload.get(name), list):
                rows = payload[name]
                break
        if rows is None:
            rows = next(
                (value for value in payload.values() if isinstance(value, list)),
                None,
            )
        if not isinstance(rows, list):
            raise RuntimeError("the payload holds no list of tickers")  # noqa: TRY004
    else:
        raise RuntimeError("the payload is neither a list nor an object")  # noqa: TRY004

    kept = [row for row in rows if isinstance(row, dict)]
    skipped = len(rows) - len(kept)
    if skipped:
        print(f"  Skipped {skipped} rows: a row must be an object.")
    return kept


def ticker_of(row: Row) -> str:
    """Return the upper-case ticker of one universe row. A miss returns ""."""
    ticker = row.get("ticker")
    return ticker.strip().upper() if isinstance(ticker, str) else ""


def base_symbol(symbol: str) -> str:
    """Return the base symbol: the asset symbol without the final "x".

    The rule matches scripts/sector_map.py, which reads the file that this
    script writes.
    """
    text = symbol.strip()
    if text[-1:].lower() == "x":
        text = text[:-1]
    return text.strip().upper()


def read_assets(path: Path = ASSETS_JSON) -> list[Row]:
    """Read the asset rows from the snapshot file. A fault stops the run.

    The filter needs the symbols, so a missing file stops the run rather than
    write every fetched row.
    """
    if not path.is_file():
        raise RuntimeError(
            f"no asset snapshot at {path}, so the filter holds no symbol list"
        )

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"cannot read the asset snapshot at {path}: {error}"
        ) from error

    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004
            f"the asset snapshot at {path} holds no list"
        )
    return [row for row in rows if isinstance(row, dict)]


def wanted_tickers(records: list[Row]) -> dict[str, set[str]]:
    """Map each asset base symbol to the ticker spellings that answer for it.

    The base symbol is the asset symbol minus the final "x". A base symbol with
    a dot also adds the dash form, and the other way around, because the
    universe spells a share class either way. "BRK.Bx" then asks for "BRK.B"
    and for "BRK-B".
    """
    wanted: dict[str, set[str]] = {}
    for record in records:
        symbol = record.get("symbol")
        if not isinstance(symbol, str):
            continue
        name = base_symbol(symbol)
        if not name:
            continue

        spellings = {name}
        if "." in name:
            spellings.add(name.replace(".", "-"))
        if "-" in name:
            spellings.add(name.replace("-", "."))
        wanted[name] = spellings
    return wanted


def filter_rows(
    rows: list[Row], wanted: dict[str, set[str]]
) -> tuple[list[Row], list[str]]:
    """Return the rows that our symbols need, and the base symbols they miss.

    A row is kept when its ticker answers for one asset base symbol. The rows
    stay untouched, so a later script reads the true field names. The miss list
    holds one base symbol per asset that no row answers.
    """
    allowed = {spelling for spellings in wanted.values() for spelling in spellings}
    kept = [row for row in rows if ticker_of(row) in allowed]
    found = {ticker_of(row) for row in kept}

    missing = sorted(
        name for name, spellings in wanted.items() if not spellings & found
    )
    return kept, missing


def row_type(row: Row) -> str:
    """Return the security type of one universe row. A miss returns ""."""
    kind = row.get("security_type")
    return kind.strip() if isinstance(kind, str) else ""


def winning_type(group: list[Row]) -> str | None:
    """Return the type that decides one ticker group, or None.

    The first type of TYPE_ORDER that the group holds wins. A group with no
    known type returns None, because any row of that group can still win.
    """
    kinds = {row_type(row) for row in group}
    for kind in TYPE_ORDER:
        if kind in kinds:
            return kind
    return None


def keep_best_type(rows: list[Row]) -> tuple[list[Row], list[Row]]:
    """Return the rows that can win, and the rows that cannot.

    A ticker can hold rows of more than one type, because two issuers can use
    the same ticker. Only the rows of the winning type can decide a value, so
    the other rows drop. The row order stays as it arrived.
    """
    groups: dict[str, list[Row]] = {}
    for row in rows:
        groups.setdefault(ticker_of(row), []).append(row)

    best = {ticker: winning_type(group) for ticker, group in groups.items()}
    kept = [row for row in rows if best[ticker_of(row)] in (None, row_type(row))]
    shadowed = [
        row for row in rows if best[ticker_of(row)] not in (None, row_type(row))
    ]
    return kept, shadowed


def load_previous_count(path: Path) -> int | None:
    """Read the fetched row count of the previous run.

    The guard needs the size of the fetched payload, so this reads the
    universeCount field. A file from before the filter holds that count in the
    count field, because every fetched row was then written.
    """
    if not path.is_file():
        return None

    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(
            f"Warning: cannot read the previous count from {path}: {error}",
            file=sys.stderr,
        )
        return None

    if not isinstance(body, dict):
        return None
    for field in ("universeCount", "count"):
        count = body.get(field)
        if isinstance(count, int) and not isinstance(count, bool):
            return count
    return None


def write_outputs(rows: list[Row], fetched_at: str, universe_count: int) -> None:
    """Write the JSON snapshot. The rows stay exactly as the API returned them."""
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": UNIVERSE_URL,
        "fetchedAt": fetched_at,
        "universeCount": universe_count,
        "count": len(rows),
        "tickers": rows,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    OUT_JSON.write_text(text + "\n", encoding="utf-8")


def keep_payload(rows: list[Row], previous: int | None, force: bool) -> None:
    """Stop the run when the payload looks cut. The old file then stands.

    The count is the fetched payload, not the kept rows, so the guard watches
    the fetch itself. With force set, a thin payload still reaches the write.
    """
    if not rows:
        raise RuntimeError(
            "the endpoint returned no rows, so the script kept the old file"
        )

    if force:
        return
    if previous and len(rows) < previous * MIN_KEEP_RATIO:
        raise RuntimeError(
            f"{len(rows)} rows is below {MIN_KEEP_RATIO:.0%} of the previous "
            f"{previous}. Pass --force to write anyway."
        )


def run(args: argparse.Namespace) -> int:
    """Fetch the universe, keep the rows of our symbols, and write the snapshot."""
    key, source = read_api_key(args.api_key_file)
    previous = load_previous_count(OUT_JSON)
    assets = read_assets()
    wanted = wanted_tickers(assets)

    print(f"Key source: {source}")
    print(f"Assets: {len(assets)}, base symbols: {len(wanted)}")
    print("Fetching the ticker universe...")
    payload = http_client.fetch_json(
        f"{UNIVERSE_URL}?api_key={key}", raise_on_auth=True, label=UNIVERSE_URL
    )
    rows = universe_rows(payload)
    kept, missing = filter_rows(rows, wanted)
    kept, shadowed = keep_best_type(kept)

    print(f"Rows: {len(rows)}")
    print(f"Kept: {len(kept)} rows for our symbols")
    if missing:
        print(f"No universe row for {len(missing)} base symbols.")
    if shadowed:
        print(f"Dropped {len(shadowed)} lower-type rows.")
    if previous is not None:
        print(f"Previous run: {previous}")
    if kept:
        print(f"Row fields: {', '.join(sorted(kept[0]))}")

    keep_payload(rows, previous, args.force)

    if args.dry_run:
        print(f"Dry run: no write. {OUT_JSON} keeps its content.")
        return 0

    write_outputs(
        kept,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        len(rows),
    )
    print(f"Wrote {len(kept)} tickers to {OUT_JSON}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch the ticker universe of our symbols into one JSON file.",
        epilog=(
            "The key comes from the environment variable, then --api-key-file, "
            f"then {KEY_MODULE.relative_to(REPO_ROOT)}."
        ),
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=None,
        help=(
            "Read the API key from this text file. "
            f"The {API_KEY_ENV} environment variable comes first."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report, and write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write a small payload anyway.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except RuntimeError as error:
        print(f"Error: {redact(str(error))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
