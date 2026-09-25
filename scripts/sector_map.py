#!/usr/bin/env python3
"""
Match every xStock symbol to a sector from the BusinessQuant ticker universe.

The universe file holds one row per listed ticker. This script groups the rows
of one ticker, picks one row, and writes that row's sector, industry, exchange,
and CIK on the asset row.

The base symbol is the asset symbol minus the final "x". "SPYx" becomes "SPY".

The match rules, in order:
  1. Group the rows of one ticker by security_type, in this order:
     Equity, ETF, Fund, Index.
  2. An Equity row gives its own sector field.
  3. An ETF, Fund, or Index row gives its own security_type. An ETF with no
     sector then reads "ETF", because a fund holds no sector.
  4. The first group with a value wins. An Equity group with no sector reads
     "unknown", and so does a ticker with no row.

The industry, the exchange, and the CIK come from the same picked row. A value
that the universe misses reads null, so the page can leave that label out. The
CIK is the SEC central index key, and it stays a number.

An asset with no universe row reads a null CIK. A row that a later run loses
keeps the CIK of the last run, in the same way as the industry and the exchange.

A manual override in data/sector_overrides.json wins over every rule above. The
key is the base symbol, and the value is the sector. Use that file for a symbol
that the universe misses, or for a symbol that the feed drops. Put a fund in as
"ETF". An override sets the sector only, so the industry and the exchange still
come from the universe.

A manual industry override lives in data/industry_overrides.json. The shape
matches the sector file: the key is the base symbol and the value is the
industry. It wins over the universe row, and it leaves the sector alone.

A base symbol with a dot retries with a dash, and the other way around.
"BRK.B" then reads "BRK-B".

Output: data/xstocks-assets.json
  one row per asset, with the country, the sector, the industry, the exchange,
  and the CIK after the symbol

fetch_assets.py imports this module and joins the sector on every run. The
commands here backfill an existing file without a full fetch.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/sector_map.py             # report only, and write nothing
  ./scripts/sector_map.py --write     # backfill data/xstocks-assets.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# The sector values that come from a security_type, not from a sector field.
TYPE_ORDER = ("Equity", "ETF", "Fund", "Index")

# The value for an asset with no sector answer.
UNKNOWN = "unknown"

# The counter keys of apply_sectors().
SOURCE_SECTOR = "sector"
SOURCE_TYPE = "type"
SOURCE_UNKNOWN = "unknown"
SOURCE_RETAINED = "retained"
SOURCE_OVERRIDE = "override"

# Field names. The universe file holds the ticker, the type, the sector, the
# industry, the exchange, and the CIK. The snapshot holds the symbol.
TICKER_FIELD = "ticker"
TYPE_FIELD = "security_type"
SECTOR_FIELD = "sector"
INDUSTRY_FIELD = "industry"
EXCHANGE_FIELD = "exchange"
CIK_FIELD = "cik"
UNIVERSE_ROWS_KEY = "tickers"
ASSET_SYMBOL_FIELD = "symbol"

# The field order of the asset snapshot. The sector and its three detail fields
# follow the country, so a backfill keeps the same order that fetch_assets.py
# writes.
ASSET_FIELD_ORDER = (
    "name",
    "symbol",
    "listingCountry",
    "sector",
    "industry",
    "exchange",
    "cik",
    "sharesHeld",
    "circulatingSupply",
    "price",
    "priceUpdatedAt",
    "multiplier",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_JSON = REPO_ROOT / "data" / "ticker_universe.json"
ASSETS_JSON = REPO_ROOT / "data" / "xstocks-assets.json"

# The manual sector overrides. A hand edit here survives every fetch.
OVERRIDES_JSON = REPO_ROOT / "data" / "sector_overrides.json"

# The manual industry overrides. The same shape, for the industry field.
INDUSTRY_OVERRIDES_JSON = REPO_ROOT / "data" / "industry_overrides.json"

Row = dict[str, Any]

# One universe entry: the sector label, the two detail fields, and the CIK.
# The CIK stays a number, so the entry holds more than text.
IndexEntry = dict[str, Any]

# The base-symbol map. The key is the ticker in upper case.
Index = dict[str, IndexEntry]


def base_symbol(symbol: str) -> str:
    """Return the base symbol: the asset symbol without the final "x"."""
    text = symbol.strip()
    if text[-1:].lower() == "x":
        text = text[:-1]
    return text.strip().upper()


def symbol_variants(base: str) -> list[str]:
    """Return the ticker spellings of one base symbol, in the try order.

    The universe spells a share class with a dot or with a dash, so the other
    form follows the base. "BRK.B" then reads "BRK.B", "BRK-B".
    """
    variants = [base]
    if "." in base:
        variants.append(base.replace(".", "-"))
    if "-" in base:
        variants.append(base.replace("-", "."))
    return variants


def _row_text(row: Row, field: str) -> str:
    """Return one text field of a row. A missing or empty value returns ""."""
    value = row.get(field)
    return value.strip() if isinstance(value, str) else ""


def _row_int(row: Row, field: str) -> int | None:
    """Return one number field of a row. A missing value returns None.

    A true or false value is not a number here, because Python counts a bool as
    an int.
    """
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def row_label(row: Row) -> str:
    """Return the label of one universe row.

    An Equity row gives its sector. Any other row gives its security_type,
    because a fund holds no sector. A row with no type gives its sector.
    """
    kind = _row_text(row, TYPE_FIELD)
    if kind and kind != "Equity":
        return kind
    return _row_text(row, SECTOR_FIELD)


def pick_row(rows: list[Row]) -> Row | None:
    """Return the row that decides the sector and the detail fields of a ticker.

    The type order picks the group: Equity first, then ETF, Fund, and Index. The
    first row of that group with a label wins. A group without a label gives its
    first row, so the label reads "unknown" and the detail fields still arrive.
    A ticker with no row gives None.
    """
    for kind in TYPE_ORDER:
        group = [row for row in rows if _row_text(row, TYPE_FIELD) == kind]
        for row in group:
            if row_label(row):
                return row
        if group:
            return group[0]

    for row in rows:
        if row_label(row):
            return row
    return rows[0] if rows else None


def load_rows(path: Path = UNIVERSE_JSON) -> list[Row]:
    """Read the ticker rows from the universe file. Return an empty list on a fault."""
    if not path.is_file():
        return []

    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(
            f"Warning: cannot read the universe from {path}: {error}",
            file=sys.stderr,
        )
        return []

    rows = body.get(UNIVERSE_ROWS_KEY) if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def build_index(rows: list[Row]) -> Index:
    """Build the base-symbol map. One pass over the rows.

    Every entry holds the sector label, the industry, the exchange, and the CIK
    of the same row, so the four values come from one source.
    """
    grouped: dict[str, list[Row]] = {}
    for row in rows:
        ticker = _row_text(row, TICKER_FIELD)
        if ticker:
            grouped.setdefault(ticker.upper(), []).append(row)

    index: Index = {}
    for ticker, group in grouped.items():
        row = pick_row(group)
        label = row_label(row) if row is not None else ""
        index[ticker] = {
            SECTOR_FIELD: label or UNKNOWN,
            INDUSTRY_FIELD: _row_text(row, INDUSTRY_FIELD) if row is not None else "",
            EXCHANGE_FIELD: _row_text(row, EXCHANGE_FIELD) if row is not None else "",
            CIK_FIELD: _row_int(row, CIK_FIELD) if row is not None else None,
        }
    return index


def load_index(path: Path = UNIVERSE_JSON) -> Index | None:
    """Read the universe file and build the sector map.

    Return None when the file is absent or holds no usable row, so the caller
    keeps the sector values of the previous run.
    """
    if not path.is_file():
        print(
            f"Warning: no ticker universe at {path}, so the sectors stay as they are.",
            file=sys.stderr,
        )
        return None

    rows = load_rows(path)
    if not rows:
        print(
            f"Warning: the ticker universe at {path} holds no usable row, "
            "so the sectors stay as they are.",
            file=sys.stderr,
        )
        return None
    return build_index(rows)


def read_labels(path: Path, kind: str) -> dict[str, str]:
    """Read one manual override file. Return an empty map on a fault.

    The key is the base symbol, in any case, without the final "x". The value
    is the label for the field that the file serves. An absent file reads as no
    override, with no warning. A key that starts with an underscore is a
    comment, and a key with no value drops out.
    """
    if not path.is_file():
        return {}

    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(
            f"Warning: cannot read the {kind} from {path}: {error}",
            file=sys.stderr,
        )
        return {}

    if not isinstance(body, dict):
        print(
            f"Warning: the {kind} at {path} hold no object, "
            "so the universe sets every value.",
            file=sys.stderr,
        )
        return {}

    overrides: dict[str, str] = {}
    for key, value in body.items():
        if not isinstance(key, str) or key.startswith("_"):
            continue
        symbol = key.strip().upper()
        label = value.strip() if isinstance(value, str) else ""
        if not symbol or not label or label.lower() == UNKNOWN:
            continue
        overrides[symbol] = label
    return overrides


def load_overrides(path: Path = OVERRIDES_JSON) -> dict[str, str]:
    """Read the manual sector overrides."""
    return read_labels(path, "sector overrides")


def load_industry_overrides(path: Path = INDUSTRY_OVERRIDES_JSON) -> dict[str, str]:
    """Read the manual industry overrides."""
    return read_labels(path, "industry overrides")


def entry_for(symbol: str, index: Index) -> IndexEntry | None:
    """Return the universe entry for one asset symbol.

    The spellings of one base symbol are tried in order, so a dot form and a
    dash form both answer. A symbol that the universe does not hold gives None.
    """
    for spelling in symbol_variants(base_symbol(symbol)):
        entry = index.get(spelling)
        if entry is not None:
            return entry
    return None


def sector_for(symbol: str, index: Index) -> str:
    """Return the sector label for one asset symbol. A miss returns "unknown"."""
    entry = entry_for(symbol, index)
    if entry is None:
        return UNKNOWN

    label = entry.get(SECTOR_FIELD)
    return label if isinstance(label, str) and label else UNKNOWN


def extra_value(
    entry: IndexEntry | None,
    override: str,
    symbol: str,
    previous: dict[str, Row],
    field: str,
) -> str | None:
    """Return one detail field value for an asset row.

    The manual override wins, then the universe. An entry without the value, and
    an absent universe, keep the value of the previous run. A value that no
    source holds reads None, so the page can leave the label out.
    """
    if override:
        return override

    if entry is not None:
        value = entry.get(field)
        if isinstance(value, str) and value:
            return value

    prior = previous.get(symbol, {}).get(field)
    if isinstance(prior, str) and prior:
        return prior
    return None


def cik_value(
    entry: IndexEntry | None,
    symbol: str,
    previous: dict[str, Row],
) -> int | None:
    """Return the CIK for one asset row.

    The universe is the only source, because no manual file serves this field. A
    miss keeps the value of the previous run. A value that no source holds reads
    None, so the page can leave the label out.
    """
    if entry is not None:
        value = entry.get(CIK_FIELD)
        if isinstance(value, int) and not isinstance(value, bool):
            return value

    prior = previous.get(symbol, {}).get(CIK_FIELD)
    if isinstance(prior, int) and not isinstance(prior, bool):
        return prior
    return None


def apply_sectors(
    records: list[Row],
    index: Index | None,
    previous: dict[str, Row],
    overrides: dict[str, str] | None = None,
    industry_overrides: dict[str, str] | None = None,
) -> Counter[str]:
    """Write the sector on every record. Return the count per source.

    A manual override wins over the universe. An absent overrides value reads
    the file. Without an index, the sector of the previous run stands. A
    record without a previous sector reads "unknown".

    The industry, the exchange, and the CIK follow the same rule. The CIK has no
    override file, so the universe and the previous run are its only sources.
    """
    if overrides is None:
        overrides = load_overrides()
    if industry_overrides is None:
        industry_overrides = load_industry_overrides()

    counts: Counter[str] = Counter()
    for record in records:
        symbol = record.get(ASSET_SYMBOL_FIELD)
        if not isinstance(symbol, str):
            continue

        base = base_symbol(symbol)
        entry = entry_for(symbol, index) if index is not None else None
        override = overrides.get(base)

        if override:
            label = override
            source = SOURCE_OVERRIDE
        elif index is None:
            prior = previous.get(symbol, {}).get(SECTOR_FIELD)
            label = prior if isinstance(prior, str) and prior else UNKNOWN
            source = SOURCE_RETAINED if label != UNKNOWN else SOURCE_UNKNOWN
        else:
            label = sector_for(symbol, index)
            if label == UNKNOWN:
                source = SOURCE_UNKNOWN
            elif label in TYPE_ORDER:
                source = SOURCE_TYPE
            else:
                source = SOURCE_SECTOR

        record[SECTOR_FIELD] = label
        record[INDUSTRY_FIELD] = extra_value(
            entry,
            industry_overrides.get(base, ""),
            symbol,
            previous,
            INDUSTRY_FIELD,
        )
        record[EXCHANGE_FIELD] = extra_value(
            entry, "", symbol, previous, EXCHANGE_FIELD
        )
        record[CIK_FIELD] = cik_value(entry, symbol, previous)
        counts[source] += 1
    return counts


def counts_line(counts: Counter[str]) -> str:
    """Return one report line for the sector counts."""
    parts = [
        f"{counts[SOURCE_SECTOR]} by sector",
        f"{counts[SOURCE_TYPE]} by security type",
        f"{counts[SOURCE_UNKNOWN]} unknown",
    ]
    if counts[SOURCE_OVERRIDE]:
        parts.append(f"{counts[SOURCE_OVERRIDE]} by override")
    if counts[SOURCE_RETAINED]:
        parts.append(f"{counts[SOURCE_RETAINED]} retained")
    return "Sector: " + ", ".join(parts)


def _holds_cik(record: Row) -> bool:
    """Return True when one asset row holds a CIK number."""
    value = record.get(CIK_FIELD)
    return isinstance(value, int) and not isinstance(value, bool)


def detail_counts_line(records: list[Row]) -> str:
    """Return one report line for the industry, the exchange, and the CIK coverage."""
    industry = sum(
        1
        for record in records
        if isinstance(record.get(INDUSTRY_FIELD), str) and record[INDUSTRY_FIELD]
    )
    exchange = sum(
        1
        for record in records
        if isinstance(record.get(EXCHANGE_FIELD), str) and record[EXCHANGE_FIELD]
    )
    cik = sum(1 for record in records if _holds_cik(record))
    return (
        f"Detail: {industry} with an industry, {exchange} with an exchange, "
        f"{cik} with a CIK"
    )


def label_counts(records: list[Row]) -> list[tuple[str, int]]:
    """Return the sector values with their counts, most common first."""
    values = (
        record.get(SECTOR_FIELD)
        for record in records
        if isinstance(record.get(SECTOR_FIELD), str)
    )
    return Counter(values).most_common()


def ordered_record(record: Row) -> Row:
    """Return the record with the canonical field order.

    An unknown field keeps its place, after the known fields.
    """
    known = [
        (field, record[field]) for field in ASSET_FIELD_ORDER if field in record
    ]
    extra = [
        (field, value)
        for field, value in record.items()
        if field not in ASSET_FIELD_ORDER
    ]
    return dict(known + extra)


def read_assets(path: Path = ASSETS_JSON, reason: str = "") -> list[Row]:
    """Read the asset rows from the snapshot file. A fault stops the run.

    This is the only reader of the snapshot, so every caller holds the same
    path rule, the same list check, and the same fault text. A reason names the
    need of the caller, and the absent-file message then holds it. A row that
    is not an object drops.
    """
    if not path.is_file():
        note = f", {reason}" if reason else ""
        raise RuntimeError(f"no asset snapshot at {path}{note}")

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"cannot read the asset snapshot at {path}: {error}"
        ) from error

    if not isinstance(rows, list):
        raise RuntimeError(f"the asset snapshot at {path} holds no list")  # noqa: TRY004
    return [row for row in rows if isinstance(row, dict)]


def write_assets(records: list[Row], path: Path = ASSETS_JSON) -> None:
    """Write the asset snapshot that the page reads, in the canonical field order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [ordered_record(record) for record in records]
    payload = json.dumps(ordered, indent=2, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    """Join the sector and the industry onto every asset row, then report.

    Write only on request.
    """
    records = read_assets()
    if not records:
        raise RuntimeError(f"the asset snapshot at {ASSETS_JSON} holds no asset")

    index = load_index()
    if index is not None:
        print(f"Universe: {len(index)} tickers")
    overrides = load_overrides()
    if overrides:
        print(f"Overrides: {len(overrides)} symbols")
    industry_overrides = load_industry_overrides()
    if industry_overrides:
        print(f"Industry overrides: {len(industry_overrides)} symbols")
    print(f"Assets: {len(records)}")

    # Without a universe, the records themselves hold the previous sector.
    previous = {record[ASSET_SYMBOL_FIELD]: record for record in records}
    counts = apply_sectors(records, index, previous, overrides, industry_overrides)

    print(counts_line(counts))
    print(detail_counts_line(records))
    for label, count in label_counts(records):
        print(f"  {label}: {count}")

    if not args.write:
        print(f"Dry run: no write. {ASSETS_JSON} keeps its content.")
        return 0

    write_assets(records)
    print(f"Wrote {len(records)} assets to {ASSETS_JSON}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Match xStock symbols to a sector from the ticker universe.",
        epilog=(
            f"The sector, the industry, and the CIK come from "
            f"{UNIVERSE_JSON.relative_to(REPO_ROOT)}. A manual override in "
            f"{OVERRIDES_JSON.relative_to(REPO_ROOT)} or "
            f"{INDUSTRY_OVERRIDES_JSON.relative_to(REPO_ROOT)} wins over that "
            "file. fetch_assets.py joins both on every run."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write the sector back to {ASSETS_JSON.relative_to(REPO_ROOT)}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
