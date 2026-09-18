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

Output: data/ticker_universe.json
  {
    "source": "https://data.businessquant.com/universe",
    "fetchedAt": "2026-09-15T18:18:50+00:00",
    "count": 8123,
    "tickers": [ ... one row per ticker, exactly as the API returned it ... ]
  }

The rows stay untouched, so a later script reads the true field names. The
run prints those field names.

The write is skipped when the payload holds no rows, or when the row count
falls below MIN_KEEP_RATIO of the previous run. A cut payload then keeps the
good file. Pass --force to write anyway. Pass --dry-run to write nothing.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  Put your key in scripts/bq_key.py, then run:
    ./scripts/ticker_universe.py

  Or name the key in the environment:
    BUSINESSQUANT_API_KEY=... ./scripts/ticker_universe.py

  Or name a key file:
    ./scripts/ticker_universe.py --api-key-file ~/.bq-key
"""

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

OUT_JSON = REPO_ROOT / "data" / "ticker_universe.json"

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


def load_previous_count(path: Path) -> int | None:
    """Read the row count of the previous run. This holds the last known value."""
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

    count = body.get("count") if isinstance(body, dict) else None
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    return None


def write_outputs(rows: list[Row], fetched_at: str) -> None:
    """Write the JSON snapshot. The rows stay exactly as the API returned them."""
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": UNIVERSE_URL,
        "fetchedAt": fetched_at,
        "count": len(rows),
        "tickers": rows,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    OUT_JSON.write_text(text + "\n", encoding="utf-8")


def keep_payload(rows: list[Row], previous: int | None) -> None:
    """Stop the run when the payload looks cut. The old file then stands."""
    if not rows:
        raise RuntimeError(
            "the endpoint returned no rows, so the script kept the old file"
        )

    if previous and len(rows) < previous * MIN_KEEP_RATIO:
        raise RuntimeError(
            f"{len(rows)} rows is below {MIN_KEEP_RATIO:.0%} of the previous "
            f"{previous}. Pass --force to write anyway."
        )


def run(args: argparse.Namespace) -> int:
    """Fetch the ticker universe and write the JSON snapshot."""
    key, source = read_api_key(args.api_key_file)
    previous = load_previous_count(OUT_JSON)

    print(f"Key source: {source}")
    print("Fetching the ticker universe...")
    payload = http_client.fetch_json(
        f"{UNIVERSE_URL}?api_key={key}", raise_on_auth=True, label=UNIVERSE_URL
    )
    rows = universe_rows(payload)

    print(f"Rows: {len(rows)}")
    if previous is not None:
        print(f"Previous run: {previous}")
    if rows:
        print(f"Row fields: {', '.join(sorted(rows[0]))}")

    keep_payload(rows, previous)

    if args.dry_run:
        print(f"Dry run: no write. {OUT_JSON} keeps its content.")
        return 0

    write_outputs(rows, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print(f"Wrote {len(rows)} tickers to {OUT_JSON}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch the BusinessQuant ticker universe into one JSON file.",
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
