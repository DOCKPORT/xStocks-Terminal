#!/usr/bin/env python3
"""
Build the SEC EDGAR link of every asset that holds a CIK.

The script reads data/xstocks-assets.json, which holds one row per asset. The
row holds the CIK, so the link needs no lookup and no network call. The reader
lives in scripts/sector_map.py. The link is:

  https://www.sec.gov/edgar/browse/?CIK=320193

The CIK is the only part of the link. That page lists every filing of the
company, and the insider rows stay in the list.

Output: data/sec_edgar.json
  array of { name, symbol, cik, url }
  one row per asset that holds a CIK, in the order of data/xstocks-assets.json

A row without a CIK reads no output row. The run prints that count. A run
that builds no link stops, so the saved file stands.

Pass --dry-run to write nothing.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/sec_edgar.py
  ./scripts/sec_edgar.py --dry-run
"""  # noqa: EXE001

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import sector_map

# The EDGAR company page. The CIK fills the only variable part.
BROWSE_URL = "https://www.sec.gov/edgar/browse/?CIK={cik}"

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = REPO_ROOT / "data" / "sec_edgar.json"

Row = dict[str, Any]


def browse_url(cik: int) -> str:
    """Return the EDGAR company page of one CIK.

    The page holds every filing of that company. The CIK needs no padding here,
    because the page reads the plain number.
    """
    return BROWSE_URL.format(cik=cik)


def cik_of(record: Row) -> int | None:
    """Return the CIK of one row. A row without a whole number returns None.

    A boolean is not a CIK, so that value returns None.
    """
    cik = record.get("cik")
    if isinstance(cik, bool) or not isinstance(cik, int):
        return None
    return cik


def output_rows(records: list[Row]) -> list[Row]:
    """Return one output row per asset that holds a CIK, in the field order.

    A row without a CIK gives no link, so it gives no output row.
    """
    rows: list[Row] = []
    for record in records:
        cik = cik_of(record)
        if cik is None:
            continue
        rows.append(
            {
                "name": record.get("name"),
                "symbol": record.get("symbol"),
                "cik": cik,
                "url": browse_url(cik),
            }
        )
    return rows


def missing_cik(records: list[Row]) -> int:
    """Return the count of the asset rows that hold no CIK."""
    return sum(1 for record in records if cik_of(record) is None)


def write_outputs(rows: list[Row], path: Path = OUT_JSON) -> None:
    """Write the JSON file that the page reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rows, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    """Build the EDGAR link of every asset that holds a CIK.

    A run that builds no link stops, so the saved file stands.
    """
    records = sector_map.read_assets()
    if not records:
        raise RuntimeError(
            f"the asset snapshot at {sector_map.ASSETS_JSON} holds no asset"
        )

    rows = output_rows(records)

    print(f"Assets: {len(records)}")
    print(f"Links: {len(rows)} from a CIK, {missing_cik(records)} without a CIK")

    if not rows:
        raise RuntimeError(
            f"no asset holds a CIK from {len(records)} asset rows, "
            f"so {OUT_JSON} keeps its content."
        )

    if args.dry_run:
        print(f"Dry run: no write. {OUT_JSON} keeps its content.")
        return 0

    write_outputs(rows)
    print(f"Wrote {len(rows)} rows to {OUT_JSON}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the EDGAR company link of every asset that holds a CIK.",
        epilog=(
            "The link needs the CIK only, so the run makes no network call. "
            "A row without a CIK is left out."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the counts and write nothing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
