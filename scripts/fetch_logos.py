#!/usr/bin/env python3
"""
Download the logo image for every xStock symbol in data/xstocks-assets.json.

One endpoint is used:
  GET https://xstocks-metadata.backed.fi/logos/tokens/{symbol}.png

The logo URL is derived from the symbol. The public assets endpoint returns
this exact pattern for every catalog entry, so no asset call is needed.

Output: data/logos/{symbol}.png

Behaviour:
  - Existing files are skipped. Pass --force to overwrite them.
  - Pass --check-changes to compare the saved logos with the server. The
    request carries the fingerprint of the saved file, so an unchanged image
    costs one small request and no image bytes. A changed image replaces the
    file and prints CHANGED.
  - The host rejects the default urllib User-Agent with HTTP 403, so the
    script sends its own Agent. scripts/http_client.py holds that header with
    the timeout and the retry.
  - The content type must be image/png. That check runs before the write, so
    an error page never lands in the folder.
  - A failed write leaves no partial file. A write that fails at the open step
    keeps the saved file. A failure after that removes the file.
  - A saved file of 0 bytes counts as missing, so a plain run fetches it again.
  - The script reports the counts and a missed-symbol list.
  - The exit code is non-zero when one or more downloads fail.

The logos are tracked in git. A fresh checkout holds every file, so a plain
run skips the lot. Pass --force to refresh them, or --check-changes to replace
only the logos that the server changed.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/fetch_logos.py
  ./scripts/fetch_logos.py --check-changes
  ./scripts/fetch_logos.py --force
  ./scripts/fetch_logos.py --workers 16
"""  # noqa: EXE001, RUF100

from __future__ import annotations

import argparse
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import http_client
import sector_map

LOGO_BASE = "https://xstocks-metadata.backed.fi/logos/tokens"

DEFAULT_WORKERS = 8
PROGRESS_EVERY = 25

PNG_CONTENT_TYPE = "image/png"

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
OUT_DIR = REPO_ROOT / "data" / "logos"


def load_symbols(path: Path) -> list[str]:
    """Read the symbols from the asset snapshot, in file order.

    The snapshot reader lives in scripts/sector_map.py. Raise RuntimeError when
    the file is absent or holds no symbol.
    """
    rows = sector_map.read_assets(path)
    symbols = [
        row["symbol"] for row in rows if isinstance(row.get("symbol"), str)
    ]
    if not symbols:
        raise RuntimeError(f"{path} holds no symbol.")
    return symbols


def saved_bytes(path: Path) -> bytes | None:
    """Read a saved logo. Return None when the file is absent, empty, or unreadable.

    An empty file comes from a download that stopped at the start. The caller
    then treats the symbol as missing and fetches the image again.
    """
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return payload or None


def saved_size(path: Path) -> int:
    """Return the byte count of a saved logo. A missing file reads 0.

    A count of 0 means a download that stopped at the start, so the caller
    treats the symbol as missing and fetches the image again.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0


def download_logo(symbol: str, conditional: bool) -> tuple[str, str]:
    """Fetch one logo. Return the status and the report line.

    The status is "unchanged", "ok", "changed", or "miss".

    With conditional set, the request carries the fingerprint of the saved file.
    An unchanged image then costs one small request and no image bytes. A wrong
    content type stops the call before the write, so a bad response never
    reaches the disk. The shared HTTP layer retries a transport error and stops
    on an HTTP error.

    A write that fails at the open step keeps the saved file. A failure after
    that removes the file, because the file then holds part of the image only.
    A saved file of 0 bytes reads as missing.
    """
    out_path = OUT_DIR / f"{symbol}.png"
    saved = saved_bytes(out_path) if conditional else None

    headers = {"Accept": PNG_CONTENT_TYPE}
    if saved is not None:
        headers["If-None-Match"] = f'"{hashlib.md5(saved).hexdigest()}"'

    url = f"{LOGO_BASE}/{symbol}.png"
    try:
        payload = http_client.get_bytes(
            url, headers=headers, label=url, content_type=PNG_CONTENT_TYPE
        )
    except RuntimeError as error:
        return "miss", f"MISS  {symbol} (download failed: {error})"

    if payload is None:
        return "unchanged", f"SAME  {symbol}"

    # A 200 with the saved bytes means the fingerprint of the server differs
    # from the file hash. Keep the saved file.
    if saved is not None and payload == saved:
        return "unchanged", f"SAME  {symbol}"

    try:
        handle = out_path.open("wb")
    except OSError as error:
        # The open failed, so the saved file keeps its bytes.
        return "miss", f"MISS  {symbol} (write failed: {error})"

    try:
        with handle:
            handle.write(payload)
    except OSError as error:
        # The write failed, so the file holds part of the image only.
        out_path.unlink(missing_ok=True)
        return "miss", f"MISS  {symbol} (write failed: {error})"

    if saved is None:
        return "ok", f"OK    {symbol}"
    return "changed", f"CHANGED {symbol}"



def run(args: argparse.Namespace) -> int:
    """Download every missing logo, check the saved ones, and report the result."""
    symbols = load_symbols(IN_JSON)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # A forced run downloads every logo, so a conditional request is pointless.
    conditional = args.check_changes and not args.force

    todo: list[str] = []
    skipped = 0
    for symbol in symbols:
        exists = saved_size(OUT_DIR / f"{symbol}.png") > 0
        if exists and not args.force and not args.check_changes:
            skipped += 1
            continue
        todo.append(symbol)

    print(f"{len(symbols)} symbols in the snapshot. {skipped} already saved.")

    downloaded = 0
    unchanged = 0
    changed: list[str] = []
    failed: list[str] = []
    if todo:
        print(f"Fetching {len(todo)} logos with {args.workers} workers...")
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {
                pool.submit(download_logo, symbol, conditional): symbol
                for symbol in todo
            }
            for future in as_completed(pending):
                symbol = pending[future]
                try:
                    status, line = future.result()
                except Exception as error:  # noqa: BLE001
                    status = "miss"
                    line = f"MISS  {symbol} (download failed: {error})"

                done += 1
                if status == "miss":
                    failed.append(symbol)
                    print(line)
                elif status == "changed":
                    changed.append(symbol)
                    print(line)
                elif status == "unchanged":
                    unchanged += 1
                else:
                    downloaded += 1
                if done % PROGRESS_EVERY == 0 or done == len(todo):
                    print(f"  logos: {done}/{len(todo)}")

    print()
    print(f"Logos: {len(symbols)} symbols in input")
    print(f"  downloaded: {downloaded}")
    print(f"  changed:    {len(changed)}")
    print(f"  unchanged:  {unchanged}")
    print(f"  skipped:    {skipped}")
    print(f"  failed:     {len(failed)}")
    print(f"Saved to {OUT_DIR}")

    if changed:
        print(f"Changed logos: {', '.join(changed)}")
        print("Commit the replaced files, so the new look reaches the page.")
    if failed:
        print(f"Missed symbols: {', '.join(failed)}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download the logo image for every xStock symbol into data/logos."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the logos that already exist.",
    )
    parser.add_argument(
        "--check-changes",
        action="store_true",
        help="Compare the saved logos with the server and replace the changes.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel downloads (default: {DEFAULT_WORKERS}).",
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
