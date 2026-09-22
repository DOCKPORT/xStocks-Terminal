#!/usr/bin/env python3
"""
Build the SEC EDGAR link to the newest 10-K of every equity xStock asset.

One endpoint is used:
  https://data.sec.gov/submissions/CIK##########.json

The script reads data/xstocks-assets.json, which holds one row per asset. An
equity row gives one lookup, because the row holds the CIK. Two symbols can
share a CIK, and one CIK is read once. An ETF row and a Fund row take no lookup
and no output row, because a fund files no 10-K.

The answer holds the filing list of that CIK. The script takes the newest row
whose form is 10-K. An amendment holds another form, so a "10-K/A" row never
answers.

One answer carries 1000 rows at most. The older rows sit in the chunk files that
the same answer names. The chunk files run from the newest to the oldest, so the
read stops at the first chunk that holds a 10-K. A CIK without a 10-K anywhere
reads every chunk.

The link holds three parts:
  1. the CIK as 10 digits, for example 0000320193
  2. the accession number without dashes, for example 000032019325000079
  3. the name of the main document, for example aapl-20250927.htm

Output: data/sec_edgar.json
  array of { name, symbol, cik, form, filed, period, url }
  one row per equity asset, in the order of data/xstocks-assets.json

A row without a CIK reads null. A row whose CIK holds no 10-K reads null in the
form, the filed, the period, and the url fields. The run prints those counts.

The SEC allows 10 requests a second. The calls share one pacer, and the default
gap is 0.12 seconds. Pass --min-interval to change it. The User-Agent comes from
scripts/http_client.py.

The write is skipped when the link count falls below MIN_KEEP_RATIO of the
previous run, so a failed run keeps the good file. Pass --force to write anyway.
Pass --dry-run to write nothing.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/sec_edgar.py
  ./scripts/sec_edgar.py --dry-run --workers 2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import http_client

SUBMISSIONS_URL = "https://data.sec.gov/submissions"

# The viewer host. The rest of the link follows the CIK and the accession.
VIEWER_URL = "https://www.sec.gov/ix?doc=/Archives/edgar/data"

# The only form that the script reads. An annual report holds this form.
TARGET_FORM = "10-K"

# The two sector labels that name a fund. A fund files no 10-K, so those rows
# take no lookup and no output row.
FUND_SECTORS = ("ETF", "Fund")

# The SEC allows 10 requests a second, so the gap stays above 0.1 seconds.
DEFAULT_WORKERS = 4
MIN_INTERVAL_SECONDS = 0.12
REQUEST_ATTEMPTS = 3

# A run below this share of the last run stops, so a failed run cannot replace
# a good file.
MIN_KEEP_RATIO = 0.8

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
OUT_JSON = REPO_ROOT / "data" / "sec_edgar.json"

# The field order of the output row. The link comes last.
FIELDS = ("name", "symbol", "cik", "form", "filed", "period", "url")

# The counter keys of apply_filings().
SOURCE_LINK = "link"
SOURCE_NO_FILING = "no filing"
SOURCE_NO_CIK = "no cik"

Row = dict[str, Any]

# One filing, with the values that the link needs.
Filing = dict[str, str | None]

# The newest filing per CIK.
Findings = dict[int, Filing | None]


def padded_cik(cik: int) -> str:
    """Return the CIK as 10 digits. An EDGAR path holds that form."""
    return f"{cik:010d}"


def compact_accession(accession: str) -> str:
    """Return the accession number without its two dashes."""
    return accession.replace("-", "").strip()


def filing_url(cik: int, accession: str, document: str) -> str:
    """Return the viewer link of one filing.

    The link holds the padded CIK, the compact accession number, and the name of
    the main document, in that order.
    """
    return (
        f"{VIEWER_URL}/{padded_cik(cik)}/"
        f"{compact_accession(accession)}/{document.strip()}"
    )


def _item(values: Any, index: int) -> str | None:
    """Return one entry of a parallel list. A miss, or empty text, returns None."""
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return value if isinstance(value, str) and value else None


def rows_from_block(block: Any) -> list[Filing]:
    """Return the filing rows of one block of parallel lists.

    A block holds one list per field, and the row order joins them. A block that
    is not an object, or that holds no form list, returns no row.
    """
    if not isinstance(block, dict):
        return []

    forms = block.get("form")
    if not isinstance(forms, list):
        return []

    accessions = block.get("accessionNumber")
    documents = block.get("primaryDocument")
    dates = block.get("filingDate")
    periods = block.get("reportDate")

    rows: list[Filing] = []
    for index, form in enumerate(forms):
        if not isinstance(form, str):
            continue
        rows.append(
            {
                "form": form,
                "accession": _item(accessions, index),
                "document": _item(documents, index),
                "filed": _item(dates, index),
                "period": _item(periods, index),
            }
        )
    return rows


def newest_filing(rows: list[Filing], form: str) -> Filing | None:
    """Return the newest filing of one form. None when no row holds that form.

    The filing date orders the rows, because one answer mixes many forms. An
    amendment holds another form, so a "10-K/A" row never answers a 10-K.
    """
    matches = [row for row in rows if row.get("form") == form]
    if not matches:
        return None
    return max(matches, key=lambda row: row.get("filed") or "")


def _filings_block(body: Any) -> dict[str, Any] | None:
    """Return the filings object of one submissions answer."""
    if not isinstance(body, dict):
        return None
    filings = body.get("filings")
    return filings if isinstance(filings, dict) else None


def recent_block(body: Any) -> Any:
    """Return the newest filing block of one submissions answer."""
    filings = _filings_block(body)
    return filings.get("recent") if filings is not None else None


def chunk_names(body: Any) -> list[str]:
    """Return the chunk file names of one submissions answer.

    The names run from the newest chunk to the oldest. A chunk holds the rows
    that no longer fit in the recent block.
    """
    filings = _filings_block(body)
    files = filings.get("files") if filings is not None else None
    if not isinstance(files, list):
        return []

    names: list[str] = []
    for entry in files:
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name:
            names.append(name)
    return names


def fetch_body(url: str, pacer: http_client.Pacer) -> Any:
    """Fetch one submissions answer. A fault raises RuntimeError.

    The call takes its time slot from the shared pacer first. The User-Agent
    comes from the shared HTTP layer. An HTTP error is final, so a refused call
    costs one request.
    """
    pacer.wait()
    payload = http_client.get_bytes(
        url,
        attempts=REQUEST_ATTEMPTS,
        label=url,
    )
    if payload is None:
        raise RuntimeError("the server answered HTTP 304, so no body arrived")

    try:
        return json.loads(payload)
    except ValueError as error:
        raise RuntimeError(f"the answer is not JSON: {error}") from error


def lookup(cik: int, pacer: http_client.Pacer) -> tuple[Filing | None, str | None]:
    """Return the newest 10-K of one CIK, and an error text.

    The recent block answers most CIKs, and a chunk is read only when that block
    misses the form. The chunks run from the newest to the oldest, so the read
    stops at the first 10-K.

    A fault returns no filing and an error text, so one bad CIK never stops the
    run. The text is None when no fault occurred.
    """
    url = f"{SUBMISSIONS_URL}/CIK{padded_cik(cik)}.json"
    try:
        body = fetch_body(url, pacer)
    except RuntimeError as error:
        return None, str(error)

    filing = newest_filing(rows_from_block(recent_block(body)), TARGET_FORM)
    if filing is not None:
        return filing, None

    for name in chunk_names(body):
        try:
            chunk_body = fetch_body(f"{SUBMISSIONS_URL}/{name}", pacer)
        except RuntimeError as error:
            return None, str(error)

        rows = rows_from_block(recent_block(chunk_body))
        filing = newest_filing(rows, TARGET_FORM)
        if filing is not None:
            return filing, None
    return None, None


def read_assets(path: Path = ASSETS_JSON) -> list[Row]:
    """Read the asset rows from the snapshot file. A fault stops the run."""
    if not path.is_file():
        raise RuntimeError(f"no asset snapshot at {path}")

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


def is_fund(record: Row) -> bool:
    """Return True for a fund row and for an ETF row.

    A fund files no 10-K, so those rows take no lookup and hold no output row.
    """
    sector = record.get("sector")
    return isinstance(sector, str) and sector.strip() in FUND_SECTORS


def needed_ciks(records: list[Row]) -> list[int]:
    """Return the CIK of every equity row that holds one. One CIK is read once.

    The list is sorted, so every run reads the files in the same order. A fund
    row gives no entry.
    """
    ciks: set[int] = set()
    for record in records:
        if is_fund(record):
            continue
        cik = record.get("cik")
        if isinstance(cik, bool) or not isinstance(cik, int):
            continue
        ciks.add(cik)
    return sorted(ciks)


def fetch_all(ciks: list[int], args: argparse.Namespace) -> tuple[Findings, int]:
    """Fetch one answer per CIK. Return the findings and the fault count.

    The findings hold the newest 10-K per CIK. A failed lookup counts as a fault
    and writes no filing, so one bad CIK never stops the run.
    """
    findings: Findings = {}
    if not ciks:
        return findings, 0

    faults = 0
    done = 0
    print(f"Fetching {len(ciks)} submission files with {args.workers} workers...")

    pacer = http_client.Pacer(args.min_interval)
    paced = partial(lookup, pacer=pacer)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for cik, (filing, error) in zip(ciks, pool.map(paced, ciks)):
            findings[cik] = filing
            if error is not None:
                faults += 1
                print(
                    f"Warning: lookup failed for CIK {cik}: {error}",
                    file=sys.stderr,
                )

            done += 1
            if done % 100 == 0 or done == len(ciks):
                print(f"  lookups: {done}/{len(ciks)}")
    return findings, faults


def apply_filings(records: list[Row], findings: Findings) -> Counter[str]:
    """Write the filing values on every equity record. Return the count per source.

    A fund row takes no value, because the output leaves it out. A row without a
    CIK, and a row whose CIK holds no 10-K, reads null in the four filing fields.
    """
    counts: Counter[str] = Counter()
    for record in records:
        if is_fund(record):
            continue

        cik = record.get("cik")
        if isinstance(cik, bool) or not isinstance(cik, int):
            _clear_filing(record)
            counts[SOURCE_NO_CIK] += 1
            continue

        filing = findings.get(cik)
        accession = filing.get("accession") if filing is not None else None
        document = filing.get("document") if filing is not None else None
        if not accession or not document:
            _clear_filing(record)
            counts[SOURCE_NO_FILING] += 1
            continue

        record["form"] = TARGET_FORM
        record["filed"] = filing.get("filed") if filing is not None else None
        record["period"] = filing.get("period") if filing is not None else None
        record["url"] = filing_url(cik, accession, document)
        counts[SOURCE_LINK] += 1
    return counts


def _clear_filing(record: Row) -> None:
    """Write a null in the four filing fields of one record."""
    for field in ("form", "filed", "period", "url"):
        record[field] = None


def output_rows(records: list[Row]) -> list[Row]:
    """Return one output row per equity asset, in the canonical field order."""
    return [
        {field: record.get(field) for field in FIELDS}
        for record in records
        if not is_fund(record)
    ]


def counts_line(counts: Counter[str]) -> str:
    """Return one report line for the link counts."""
    parts = [
        f"{counts[SOURCE_LINK]} from a 10-K",
        f"{counts[SOURCE_NO_FILING]} without a 10-K",
        f"{counts[SOURCE_NO_CIK]} without a CIK",
    ]
    return "Links: " + ", ".join(parts)


def load_previous_links(path: Path = OUT_JSON) -> int | None:
    """Read the link count of the previous run. This holds the last known value."""
    if not path.is_file():
        return None

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(
            f"Warning: cannot read the previous count from {path}: {error}",
            file=sys.stderr,
        )
        return None

    if not isinstance(rows, list):
        return None
    return sum(
        1
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("url"), str) and row["url"]
    )


def keep_payload(links: int, previous: int | None, force: bool) -> None:
    """Stop the run when the payload looks thin. The old file then stands."""
    if force or not previous:
        return
    if links < previous * MIN_KEEP_RATIO:
        raise RuntimeError(
            f"{links} links is below {MIN_KEEP_RATIO:.0%} of the previous "
            f"{previous}. Pass --force to write anyway."
        )


def write_outputs(rows: list[Row], path: Path = OUT_JSON) -> None:
    """Write the JSON file that the page reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rows, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    """Build the EDGAR link for every equity asset and write the JSON file."""
    records = read_assets()
    if not records:
        raise RuntimeError(f"the asset snapshot at {ASSETS_JSON} holds no asset")

    previous = load_previous_links()
    funds = sum(1 for record in records if is_fund(record))
    ciks = needed_ciks(records)

    print(f"Assets: {len(records)}")
    print(f"Funds and ETFs left out: {funds}")
    print(f"CIKs: {len(ciks)}")
    if previous is not None:
        print(f"Previous run: {previous} links")

    findings, faults = fetch_all(ciks, args)
    counts = apply_filings(records, findings)
    links = counts[SOURCE_LINK]

    print(counts_line(counts))
    if faults:
        print(f"Failed lookups: {faults}")
    keep_payload(links, previous, args.force)

    if args.dry_run:
        print(f"Dry run: no write. {OUT_JSON} keeps its content.")
        return 0

    rows = output_rows(records)
    write_outputs(rows)
    print(f"Wrote {len(rows)} rows to {OUT_JSON}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the EDGAR link of the newest annual report per asset.",
        epilog=(
            "The script reads one form only, the 10-K. An ETF row and a Fund row "
            "are left out, because a fund files no 10-K."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel lookups (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=MIN_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between lookups. Use 0 to stop pacing "
            f"(default: {MIN_INTERVAL_SECONDS})."
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
        help="Write a thin payload anyway.",
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
