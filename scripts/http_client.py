#!/usr/bin/env python3
"""
The shared HTTP layer for the scripts in this folder.

Three scripts talk to three hosts, so this module holds the parts that they
share: the User-Agent header, the timeout, the retry count, the Retry-After
read, the backoff values, the Pacer class, fetch_json, and get_bytes.

A rate-limit status waits for the Retry-After header, then backs off. A small
random part joins the wait, so two threads do not retry in step. A call that
passes a callback runs it on every rate-limit answer, so the caller can hold
every thread back. When every attempt meets a rate-limit status, fetch_json
raises RateLimitError.
A missing-resource status (404, 410) is final, so a missing symbol costs one
request. With raise_on_auth set, a rejected key raises AuthError at once. A
call that gives a label puts that label in the message in place of the URL.
Use a label when the URL holds a secret, for example an API key.

A wrong content type, or an absent file, throws RuntimeError from get_bytes.
The type check runs before the caller writes a file.

Usage:
  from http_client import Pacer, fetch_json, get_bytes

Requires: Python 3.9 or later. No third-party packages.
"""  # noqa: EXE001

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

API_USER_AGENT = "xstocks-terminal/1.0"

REQUEST_TIMEOUT_SECONDS = 60
REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2

# A rejected key stops the call at once.
AUTH_ERROR_CODES = (401, 403)

# A missing resource never appears on a retry, so this status is final.
MISSING_CODES = (404, 410)

# The quote endpoint and the logo host rate limit a burst of calls.
RATE_LIMIT_CODES = (429, 503)
RATE_LIMIT_BACKOFF_SECONDS = (2.0, 4.0, 8.0)
RATE_LIMIT_MAX_WAIT_SECONDS = 30.0

# The random part of a rate-limit wait. It keeps two threads apart.
RATE_LIMIT_JITTER_SECONDS = 1.0


class AuthError(RuntimeError):
    """The server rejected the API key."""


class RateLimitError(RuntimeError):
    """The server refused the request with a rate-limit status."""


class NotModifiedError(RuntimeError):
    """The server answered HTTP 304, so the saved body still stands."""


def describe_error(error: Exception | None) -> str:
    """Return a short error text. The text holds no URL."""
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code} {error.reason}"
    if isinstance(error, urllib.error.URLError):
        return f"{type(error).__name__}: {error.reason}"
    if error is None:
        return "no error"
    return type(error).__name__


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
    """Return the wait before a retry. Honor Retry-After, then back off.

    A small random part joins the wait, so two threads do not retry in step.
    """
    header_seconds = _retry_after_seconds(error)
    if header_seconds is not None:
        delay = header_seconds
    else:
        index = min(attempt - 1, len(RATE_LIMIT_BACKOFF_SECONDS) - 1)
        delay = RATE_LIMIT_BACKOFF_SECONDS[index]

    jitter = random.uniform(0.0, RATE_LIMIT_JITTER_SECONDS)
    return min(delay + jitter, RATE_LIMIT_MAX_WAIT_SECONDS)


class Pacer:
    """One time slot per call, shared by every thread.

    Every call takes the next slot. A call that arrives early sleeps until its
    slot. The lock keeps two threads apart. An interval of 0 returns at once.
    """

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def wait(self) -> None:
        """Hold the caller until its time slot. An interval of 0 returns at once."""
        if self._interval <= 0:
            return

        with self._lock:
            start = max(time.monotonic(), self._next_slot)
            self._next_slot = start + self._interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    attempts: int = REQUEST_ATTEMPTS,
    pacer: Pacer | None = None,
    raise_on_auth: bool = False,
    retry_http_errors: bool = True,
    label: str | None = None,
    decode: Callable[[bytes], Any] | None = None,
    on_rate_limit: Callable[[], None] | None = None,
) -> tuple[Any, str]:
    """Fetch one URL. Return the body and the content type.

    A rate-limit status waits, then backs off. A rejected key raises AuthError.
    HTTP 304 raises NotModifiedError. A missing-resource status is final, so a
    retry stops at once. The decode sits inside the retry loop, so a broken
    body retries. With on_rate_limit set, each rate-limit answer runs that
    callback before the wait, so the caller can hold the other threads back.
    """
    name = label or url
    request = urllib.request.Request(
        url, headers={"User-Agent": API_USER_AGENT, **(headers or {})}
    )
    last_error: Exception | None = None
    rate_limited = False

    for attempt in range(1, attempts + 1):
        if pacer is not None:
            pacer.wait()
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type", "")
            value = decode(payload) if decode is not None else payload
            return value, content_type
        except urllib.error.HTTPError as error:
            if error.code == 304:
                raise NotModifiedError(f"not modified: {name}") from error
            last_error = error
            if raise_on_auth and error.code in AUTH_ERROR_CODES:
                raise AuthError(
                    f"the API key was rejected with HTTP {error.code}. "
                    "Check the key."
                ) from error
            if error.code in RATE_LIMIT_CODES:
                rate_limited = True
                if on_rate_limit is not None:
                    on_rate_limit()
                if attempt < attempts:
                    time.sleep(_rate_limit_delay(error, attempt))
                continue
            if error.code in MISSING_CODES:
                break
            if not retry_http_errors:
                break
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SECONDS)
        except (OSError, ValueError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SECONDS)

    if rate_limited:
        raise RateLimitError(f"rate limited: {name}: {describe_error(last_error)}")
    raise RuntimeError(f"request failed: {name}: {describe_error(last_error)}")


def fetch_json(
    url: str,
    attempts: int = REQUEST_ATTEMPTS,
    *,
    pacer: Pacer | None = None,
    raise_on_auth: bool = False,
    label: str | None = None,
) -> Any:
    """Fetch one URL and decode the JSON body.

    With pacer set, the call waits for its time slot first. With raise_on_auth
    set, a rejected key raises AuthError, and no retry follows. Name a label
    when the URL holds a secret, because the message then holds the label only.
    """
    value, _ = _request(
        url,
        attempts=attempts,
        pacer=pacer,
        raise_on_auth=raise_on_auth,
        label=label,
        decode=json.loads,
    )
    return value


def get_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    attempts: int = REQUEST_ATTEMPTS,
    label: str | None = None,
    content_type: str | None = None,
    pacer: Pacer | None = None,
    on_rate_limit: Callable[[], None] | None = None,
) -> bytes | None:
    """Fetch a raw body. Return None when the server answers HTTP 304.

    With content_type set, a different type raises RuntimeError, so a bad
    answer never reaches the disk. A rate-limit status waits and retries; every
    other HTTP error is final, so a missing file costs one request. A transport
    error retries. With pacer set, each attempt waits for its time slot. With
    on_rate_limit set, a rate-limit answer runs that callback.
    """
    name = label or url
    try:
        payload, found_type = _request(
            url,
            headers=headers,
            attempts=attempts,
            retry_http_errors=False,
            label=name,
            pacer=pacer,
            on_rate_limit=on_rate_limit,
        )
    except NotModifiedError:
        return None

    if content_type is not None:
        found = found_type.split(";")[0].strip().lower()
        if found != content_type:
            raise RuntimeError(f"unexpected content type from {name}: {found_type}")
    return payload
