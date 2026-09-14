"""
US equity market calendar.

One module holds every trading-day rule:

  - The ten US market holidays for a year.
  - The trading-day test.
  - The session test.

The session has two legs:
  - Overnight: 20:00 ET to 04:00 ET. It starts on Sunday night and ends on
    Friday morning.
  - Day: 04:00 ET to 20:00 ET. This covers pre-market, regular, and
    after-hours trading, Monday to Friday.

No leg runs into a weekend or a holiday. A holiday that falls on a Monday
closes the Sunday-night leg. A holiday that falls on a Friday closes the
Thursday-night leg.

Requires: Python 3.9 or later. No third-party packages.

Usage:
  from market_calendar import MARKET_ZONE, market_is_open
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

MARKET_ZONE = ZoneInfo("America/New_York")

# The overnight leg starts at 20:00 ET and ends at 04:00 ET.
OVERNIGHT_OPEN = clock_time(20, 0)
OVERNIGHT_CLOSE = clock_time(4, 0)

# The overnight leg starts on Sunday night (6) through Thursday night (3).
OVERNIGHT_START_DAYS = frozenset({6, 0, 1, 2, 3})


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    """Return the nth given weekday of a month. Monday is 0."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last given weekday of a month. Monday is 0."""
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed(day: date) -> date:
    """Shift a fixed holiday off the weekend, as the exchange does."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter_sunday(year: int) -> date:
    """Return Easter Sunday. Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    leap = (32 + 2 * e + 2 * i - h - k) % 7
    correction = (a + 11 * h + 22 * leap) // 451
    month = (h + leap - 7 * correction + 114) // 31
    day = ((h + leap - 7 * correction + 114) % 31) + 1
    return date(year, month, day)


def us_market_holidays(year: int) -> set[date]:
    """Return the ten US market holidays for one year."""
    return {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }


def _holidays_near(day: date) -> set[date]:
    """Return the holidays for the current year and the next year.

    The next year is included, because an observed New Year's Day can fall in
    December.
    """
    return us_market_holidays(day.year) | us_market_holidays(day.year + 1)


def is_trading_day(day: date) -> bool:
    """True when the US market holds a session on that calendar day."""
    if day.weekday() >= 5:
        return False
    return day not in _holidays_near(day)


def market_is_open(moment: datetime) -> bool:
    """True during the US overnight, pre-market, regular, or after-hours session."""
    local = moment.astimezone(MARKET_ZONE)
    if local.time() >= OVERNIGHT_OPEN:
        # The overnight leg runs Sunday night through Thursday night. It does
        # not run into a weekend or a holiday.
        return (
            local.weekday() in OVERNIGHT_START_DAYS
            and is_trading_day(local.date() + timedelta(days=1))
        )
    return is_trading_day(local.date())
