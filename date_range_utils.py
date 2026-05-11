"""
Date range utilities for GAQL queries.

Supports two input styles for the `date_range` parameter throughout the MCP:

1. Google Ads predefined date range enums (case-insensitive), e.g.:
   - "TODAY", "YESTERDAY"
   - "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"
   - "THIS_MONTH", "LAST_MONTH"
   - "THIS_WEEK_MON_TODAY", "THIS_WEEK_SUN_TODAY"
   - "LAST_WEEK_MON_SUN", "LAST_WEEK_SUN_SAT"
   - "LAST_BUSINESS_WEEK"

2. Custom date ranges with explicit start/end dates (ISO format YYYY-MM-DD).
   Any of the following separators are accepted:
   - "2025-01-01,2025-01-31"
   - "2025-01-01..2025-01-31"
   - "2025-01-01:2025-01-31"
   - "2025-01-01|2025-01-31"
   - "2025-01-01 to 2025-01-31"
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Tuple


GOOGLE_ADS_DATE_RANGES = frozenset({
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "LAST_BUSINESS_WEEK",
    "LAST_MONTH",
    "LAST_WEEK_MON_SUN",
    "LAST_WEEK_SUN_SAT",
    "THIS_MONTH",
    "THIS_WEEK_MON_TODAY",
    "THIS_WEEK_SUN_TODAY",
    "THIS_YEAR",
    "LAST_YEAR",
    "ALL_TIME",
})


_CUSTOM_RANGE_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})\s*(?:,|\.{2,3}|:|\||->|to|TO)\s*(\d{4}-\d{2}-\d{2})\s*$"
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidDateRangeError(ValueError):
    """Raised when a date_range string cannot be parsed."""


def _validate_iso_date(value: str) -> date:
    """Validate that `value` is a real ISO date (YYYY-MM-DD)."""
    if not _ISO_DATE_RE.match(value):
        raise InvalidDateRangeError(
            f"Invalid date '{value}'. Expected ISO format YYYY-MM-DD."
        )
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise InvalidDateRangeError(f"Invalid date '{value}': {e}") from e


def parse_custom_date_range(date_range: str) -> Tuple[str, str] | None:
    """Return (start, end) as ISO strings if `date_range` is a custom range, else None.

    Raises InvalidDateRangeError if a custom-looking range has invalid dates or
    the start is after the end.
    """
    if not isinstance(date_range, str):
        return None

    match = _CUSTOM_RANGE_RE.match(date_range)
    if not match:
        return None

    start_str, end_str = match.group(1), match.group(2)
    start_d = _validate_iso_date(start_str)
    end_d = _validate_iso_date(end_str)

    if start_d > end_d:
        raise InvalidDateRangeError(
            f"Invalid date range: start '{start_str}' is after end '{end_str}'."
        )

    return start_str, end_str


def is_predefined_range(date_range: str) -> bool:
    """Return True if `date_range` matches a Google Ads predefined enum."""
    if not isinstance(date_range, str):
        return False
    return date_range.strip().upper() in GOOGLE_ADS_DATE_RANGES


def build_date_filter(
    date_range: str | None,
    field: str = "segments.date",
) -> str:
    """Build the SQL fragment for filtering on a date field.

    Accepts either a Google Ads enum (LAST_30_DAYS, ...) or a custom range
    string (e.g. "2025-01-01,2025-01-31").

    The returned fragment does NOT include "WHERE" or "AND" - it is the
    predicate only, e.g. `segments.date DURING LAST_30_DAYS` or
    `segments.date BETWEEN '2025-01-01' AND '2025-01-31'`.

    Args:
        date_range: Either a predefined enum or a custom range string.
            If falsy/None, defaults to LAST_30_DAYS.
        field: GAQL field to filter on. Defaults to "segments.date".

    Returns:
        A predicate string usable inside a GAQL WHERE clause.

    Raises:
        InvalidDateRangeError: If the input looks like a custom range but
            contains invalid dates, or if it is not a recognised enum.
    """
    if not date_range:
        return f"{field} DURING LAST_30_DAYS"

    value = str(date_range).strip()

    # Custom range first (more specific pattern).
    custom = parse_custom_date_range(value)
    if custom is not None:
        start, end = custom
        return f"{field} BETWEEN '{start}' AND '{end}'"

    upper = value.upper()
    if upper in GOOGLE_ADS_DATE_RANGES:
        return f"{field} DURING {upper}"

    raise InvalidDateRangeError(
        f"Unrecognised date_range '{date_range}'. "
        "Use a Google Ads enum (e.g. LAST_30_DAYS, THIS_MONTH) or a custom "
        "range like '2025-01-01,2025-01-31'."
    )


def resolve_date_range(
    date_range: str | None,
    today: date | None = None,
) -> Tuple[str, str]:
    """Resolve any supported `date_range` value to a concrete (start, end) pair.

    This is useful for computing comparison periods or for tools that need
    explicit ISO dates rather than the GAQL `DURING` syntax.

    Args:
        date_range: Either an enum (LAST_30_DAYS, ...) or a custom range.
        today: Optional reference date. Defaults to date.today(). Useful for
            tests or to anchor against an account's timezone.

    Returns:
        Tuple of (start_iso, end_iso). Both are inclusive ISO strings.

    Raises:
        InvalidDateRangeError: If the input cannot be resolved.
    """
    if today is None:
        today = date.today()

    if not date_range:
        date_range = "LAST_30_DAYS"

    value = str(date_range).strip()

    custom = parse_custom_date_range(value)
    if custom is not None:
        return custom

    upper = value.upper()
    if upper not in GOOGLE_ADS_DATE_RANGES:
        raise InvalidDateRangeError(
            f"Unrecognised date_range '{date_range}'."
        )

    end = today
    if upper == "TODAY":
        start = today
    elif upper == "YESTERDAY":
        start = today - timedelta(days=1)
        end = start
    elif upper == "LAST_7_DAYS":
        start = today - timedelta(days=7)
        end = today - timedelta(days=1)
    elif upper == "LAST_14_DAYS":
        start = today - timedelta(days=14)
        end = today - timedelta(days=1)
    elif upper == "LAST_30_DAYS":
        start = today - timedelta(days=30)
        end = today - timedelta(days=1)
    elif upper == "LAST_90_DAYS":
        start = today - timedelta(days=90)
        end = today - timedelta(days=1)
    elif upper == "THIS_MONTH":
        start = today.replace(day=1)
        end = today
    elif upper == "LAST_MONTH":
        first_of_this_month = today.replace(day=1)
        last_of_last_month = first_of_this_month - timedelta(days=1)
        start = last_of_last_month.replace(day=1)
        end = last_of_last_month
    elif upper == "THIS_WEEK_MON_TODAY":
        start = today - timedelta(days=today.weekday())
        end = today
    elif upper == "THIS_WEEK_SUN_TODAY":
        # Sunday is weekday 6; offset so that Sunday becomes the week start.
        offset = (today.weekday() + 1) % 7
        start = today - timedelta(days=offset)
        end = today
    elif upper == "LAST_WEEK_MON_SUN":
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        end = this_monday - timedelta(days=1)
    elif upper == "LAST_WEEK_SUN_SAT":
        offset = (today.weekday() + 1) % 7
        this_sunday = today - timedelta(days=offset)
        start = this_sunday - timedelta(days=7)
        end = this_sunday - timedelta(days=1)
    elif upper == "LAST_BUSINESS_WEEK":
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        end = start + timedelta(days=4)
    elif upper == "THIS_YEAR":
        start = today.replace(month=1, day=1)
        end = today
    elif upper == "LAST_YEAR":
        start = today.replace(year=today.year - 1, month=1, day=1)
        end = today.replace(year=today.year - 1, month=12, day=31)
    elif upper == "ALL_TIME":
        start = date(2000, 1, 1)
        end = today
    else:
        raise InvalidDateRangeError(
            f"Unrecognised date_range '{date_range}'."
        )

    return start.isoformat(), end.isoformat()


def previous_period(
    start: str,
    end: str,
    mode: str = "preceding",
) -> Tuple[str, str]:
    """Compute a comparison "previous" period from a current (start, end) range.

    Args:
        start: Current period start (ISO YYYY-MM-DD).
        end: Current period end (ISO YYYY-MM-DD).
        mode: Either "preceding" (default; the immediately preceding window of
            the same length) or "year_over_year" (the same window shifted back
            by exactly one year).

    Returns:
        Tuple (prev_start, prev_end) as ISO strings.
    """
    start_d = _validate_iso_date(start)
    end_d = _validate_iso_date(end)

    if start_d > end_d:
        raise InvalidDateRangeError(
            f"Invalid range: start '{start}' is after end '{end}'."
        )

    mode_lower = (mode or "preceding").lower()

    if mode_lower in ("preceding", "previous", "prior"):
        length_days = (end_d - start_d).days + 1
        prev_end = start_d - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length_days - 1)
        return prev_start.isoformat(), prev_end.isoformat()

    if mode_lower in ("year_over_year", "yoy", "yearoveryear"):
        try:
            prev_start = start_d.replace(year=start_d.year - 1)
        except ValueError:
            # Feb 29 -> Feb 28 fallback
            prev_start = start_d.replace(year=start_d.year - 1, day=28)
        try:
            prev_end = end_d.replace(year=end_d.year - 1)
        except ValueError:
            prev_end = end_d.replace(year=end_d.year - 1, day=28)
        return prev_start.isoformat(), prev_end.isoformat()

    raise InvalidDateRangeError(
        f"Unknown comparison mode '{mode}'. Use 'preceding' or 'year_over_year'."
    )
