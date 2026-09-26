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
  - The calls share one pacer. The default gap is 0.25 seconds. Pass
    --min-interval to change the gap.
  - A rate-limit answer pauses every call for 60 seconds and doubles the gap.
    A later answer stops the check. The saved files stand, and the next run
    covers the stopped symbols.
  - The host rejects the default urllib User-Agent with HTTP 403, so the
    script sends its own Agent. scripts/http_client.py holds that header with
    the timeout and the retry.
  - The content type must be image/png. That check runs before the write, so
    an error page never lands in the folder.
  - A failed write leaves no partial file. A write that fails at the open step
    keeps the saved file. A failure after that removes the file.
  - A saved file of 0 bytes counts as missing, so a plain run fetches it again.
  - The script reports the counts and the symbol lists.
  - The exit code is non-zero when one or more calls fail or stop. The parent
    script scripts/fetch_assets.py reports that code as one warning.

The logos are tracked in git. A fresh checkout holds every file, so a plain
run skips the lot. Pass --force to refresh them, or --check-changes to replace
only the logos that the server changed.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  ./scripts/fetch_logos.py
  ./scripts/fetch_logos.py --check-changes
  ./scripts/fetch_logos.py --force
  ./scripts/fetch_logos.py --workers 6
  ./scripts/fetch_logos.py --min-interval 0.5
"""  # noqa: EXE001, RUF100

from __future__ import annotations

import argparse
import hashlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import http_client
import sector_map

LOGO_BASE = "https://xstocks-metadata.backed.fi/logos/tokens"

DEFAULT_WORKERS = 6

# The default gap between two logo calls, in seconds. The host answers a burst
# with HTTP 429, so the calls share one pacer.
DEFAULT_INTERVAL_SECONDS = 0.25

# The logo call keeps its own attempt count, because a rate-limit answer costs
# a real wait. LOGO_ATTEMPTS counts every try, so five tries hold four waits.
LOGO_ATTEMPTS = 5

# A rate-limit answer pauses every call for this long.
COOLDOWN_SECONDS = 60.0

# One pause is allowed. A rate-limit answer past that count stops the check.
RATE_LIMIT_PAUSES = 1

PROGRESS_EVERY = 25

PNG_CONTENT_TYPE = "image/png"

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_JSON = REPO_ROOT / "data" / "xstocks-assets.json"
OUT_DIR = REPO_ROOT / "data" / "logos"


class Throttle:
    """Hold the logo calls back when the host answers a rate-limit status.

    Every worker shares one object. The first rate-limit answer closes the gate
    for COOLDOWN_SECONDS and doubles the gap between two calls, so the run goes
    easier after the pause. An answer past RATE_LIMIT_PAUSES keeps the gate
    closed, so the run then stops and makes no more calls.

    The class owns the pacer of the logo calls. The quote calls keep their own
    pacer in scripts/backed_api.py.
    """

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        cooldown: float = COOLDOWN_SECONDS,
        pauses: int = RATE_LIMIT_PAUSES,
    ) -> None:
        self._lock = threading.Lock()
        self._interval = max(0.0, interval)
        self._cooldown = max(0.0, cooldown)
        self._pauses = max(0, pauses)
        self._gate_pauses = 0
        self._trips = 0
        self._open_at = 0.0
        self._stopped = False
        self._pacer = http_client.Pacer(self._interval)

    @property
    def interval(self) -> float:
        """Return the current gap between two calls, in seconds."""
        return self._interval

    @property
    def trips(self) -> int:
        """Return the count of the rate-limit answers."""
        with self._lock:
            return self._trips

    @property
    def pacer(self) -> http_client.Pacer:
        """Return the pacer that every call shares."""
        return self._pacer

    def wait(self) -> bool:
        """Hold the caller for the pause. Return False when the run stops.

        The gate opens again when the pause ends. A stopped gate never opens,
        so the caller makes no call and leaves at once.
        """
        while True:
            with self._lock:
                if self._stopped:
                    return False
                delay = self._open_at - time.monotonic()
            if delay <= 0:
                return True
            time.sleep(min(delay, 1.0))

    def trip(self) -> None:
        """Note one rate-limit answer. This method is the notify callback.

        An answer that arrives while the gate holds joins the same pause,
        because the workers meet one rate limit together. An answer that opens
        a pause past the limit stops the run.
        """
        with self._lock:
            self._trips += 1
            if time.monotonic() < self._open_at:
                return
            if self._gate_pauses >= self._pauses:
                if not self._stopped:
                    self._stopped = True
                    print("Rate limited again. The logo check stops here.")
                return
            self._gate_pauses += 1
            self._open_at = time.monotonic() + self._cooldown
            if self._interval > 0:
                self._interval *= 2
            self._pacer = http_client.Pacer(self._interval)
            print(
                f"Rate limited. Every call pauses for {self._cooldown:g} seconds,"
                f" then the gap grows to {self._interval:g} seconds."
            )


@dataclass(frozen=True)
class Batch:
    """The result of one block of logo calls.

    A symbol of the failed list ended with no verdict, because the host refused
    the last try. A symbol of the limited list ended on a rate-limit answer. A
    symbol of the stopped list met a closed gate, so it cost no call.
    """

    downloaded: int = 0
    unchanged: int = 0
    changed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    limited: tuple[str, ...] = ()
    stopped: tuple[str, ...] = ()

    def merge(self, other: Batch) -> Batch:
        """Return one result that holds the counts and the lists of both."""
        return Batch(
            downloaded=self.downloaded + other.downloaded,
            unchanged=self.unchanged + other.unchanged,
            changed=self.changed + other.changed,
            failed=self.failed + other.failed,
            limited=self.limited + other.limited,
            stopped=self.stopped + other.stopped,
        )


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


def download_logo(
    symbol: str, conditional: bool, throttle: Throttle
) -> tuple[str, str]:
    """Fetch one logo. Return the status and the report line.

    The status is "unchanged", "ok", "changed", "miss", "limited", or
    "stopped". A stopped status means that the gate of the throttle holds the
    calls, so this symbol costs no request.

    With conditional set, the request carries the fingerprint of the saved file.
    An unchanged image then costs one small request and no image bytes. A wrong
    content type stops the call before the write, so a bad response never
    reaches the disk. The shared HTTP layer retries a transport error and a
    rate-limit answer, and it stops on another HTTP error.

    A write that fails at the open step keeps the saved file. A failure after
    that removes the file, because the file then holds part of the image only.
    A saved file of 0 bytes reads as missing.
    """
    if not throttle.wait():
        return "stopped", f"STOP  {symbol}"

    out_path = OUT_DIR / f"{symbol}.png"
    saved = saved_bytes(out_path) if conditional else None

    headers = {"Accept": PNG_CONTENT_TYPE}
    if saved is not None:
        headers["If-None-Match"] = f'"{hashlib.md5(saved).hexdigest()}"'

    url = f"{LOGO_BASE}/{symbol}.png"
    try:
        payload = http_client.get_bytes(
            url,
            headers=headers,
            label=url,
            content_type=PNG_CONTENT_TYPE,
            attempts=LOGO_ATTEMPTS,
            pacer=throttle.pacer,
            on_rate_limit=throttle.trip,
        )
    except http_client.RateLimitError as error:
        return "limited", f"LIMIT {symbol} (download failed: {error})"
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



def _fetch_batch(
    symbols: list[str], conditional: bool, workers: int, throttle: Throttle
) -> Batch:
    """Run one block of logo calls. Return the counts and the symbol lists.

    The pool holds the worker count. The throttle gates every call, so the call
    rate follows the gap and not the worker count.
    """
    if not symbols:
        return Batch()

    downloaded = 0
    unchanged = 0
    changed: list[str] = []
    failed: list[str] = []
    limited: list[str] = []
    stopped: list[str] = []

    print(f"Fetching {len(symbols)} logos with {workers} workers...")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {
            pool.submit(download_logo, symbol, conditional, throttle): symbol
            for symbol in symbols
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
            elif status == "limited":
                limited.append(symbol)
                print(line)
            elif status == "stopped":
                stopped.append(symbol)
            elif status == "changed":
                changed.append(symbol)
                print(line)
            elif status == "unchanged":
                unchanged += 1
            else:
                downloaded += 1
            if done % PROGRESS_EVERY == 0 or done == len(symbols):
                print(f"  logos: {done}/{len(symbols)}")

    return Batch(
        downloaded=downloaded,
        unchanged=unchanged,
        changed=tuple(changed),
        failed=tuple(failed),
        limited=tuple(limited),
        stopped=tuple(stopped),
    )


def run(args: argparse.Namespace) -> int:
    """Download every missing logo, check the saved ones, and report the result.

    The calls share one pacer, so the host sees a steady rate. A rate-limit
    answer pauses every call, and a late answer stops the check. A stopped or a
    failed symbol keeps its saved file, so the next run covers it again.
    """
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
    if args.min_interval > 0:
        print(f"Call gap: {args.min_interval:g} seconds.")

    throttle = Throttle(args.min_interval, COOLDOWN_SECONDS)
    result = _fetch_batch(todo, conditional, args.workers, throttle)

    retry = result.limited + result.failed
    if retry:
        # A rate-limit window clears with time, so the symbols that hold no
        # verdict get one more try. One call at a time holds a small count.
        if throttle.trips:
            print(f"Pausing {COOLDOWN_SECONDS:g} seconds before the second pass...")
            time.sleep(COOLDOWN_SECONDS)
        print(f"Second pass over {len(retry)} symbols, one call at a time...")
        result = result.merge(
            _fetch_batch(
                retry, conditional, 1, Throttle(throttle.interval, COOLDOWN_SECONDS)
            )
        )

    print()
    print(f"Logos: {len(symbols)} symbols in input")
    print(f"  downloaded: {result.downloaded}")
    print(f"  changed:    {len(result.changed)}")
    print(f"  unchanged:  {result.unchanged}")
    print(f"  skipped:    {skipped}")
    print(f"  failed:     {len(result.failed)}")
    print(f"  limited:    {len(result.limited)}")
    print(f"  stopped:    {len(result.stopped)}")
    print(f"Saved to {OUT_DIR}")

    if result.changed:
        print(f"Changed logos: {', '.join(result.changed)}")
        print("Commit the replaced files, so the new look reaches the page.")
    missed = result.failed + result.limited
    if missed:
        print(f"Missed symbols: {', '.join(missed)}")
    if result.stopped:
        print(
            f"Stopped symbols: {len(result.stopped)}. The host rate limited the "
            "calls. The saved files stand, and the next run covers them."
        )
    if throttle.trips:
        print(f"Rate-limit answers: {throttle.trips}")
    if missed or result.stopped:
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
    parser.add_argument(
        "--min-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between logo calls. Use 0 to stop pacing "
            f"(default: {DEFAULT_INTERVAL_SECONDS})."
        ),
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
