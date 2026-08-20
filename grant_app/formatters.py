"""Format probabilities, CAD amounts, and timestamps for display in Jinja templates."""

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo


VANCOUVER_TIMEZONE = ZoneInfo("America/Vancouver")


def probability_percent(value: Decimal) -> str:
    """Format a decimal probability as a percentage with two decimal places.

    Args:
        value: A probability represented as a decimal fraction.

    Returns:
        A display string such as ``"52.34%"``.
    """
    return f"{value * Decimal('100'):.2f}%"


def cad_currency(value: Decimal) -> str:
    """Format an exact decimal amount as Canadian currency.

    Args:
        value: The monetary amount in Canadian dollars.

    Returns:
        A grouped, two-decimal display string ending in ``"CAD"``.
    """
    return f"${value:,.2f} CAD"


def vancouver_datetime(value: datetime) -> str:
    """Convert a timestamp to a readable date and time in Vancouver.

    Args:
        value: A timezone-aware timestamp, or a naive timestamp interpreted as
            UTC for compatibility with SQLite values.

    Returns:
        A localized string containing the date, time, meridiem, and timezone
        abbreviation.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)

    localized = value.astimezone(VANCOUVER_TIMEZONE)
    hour = localized.strftime("%I").lstrip("0") or "0"
    return (
        f"{localized.strftime('%B')} {localized.day}, {localized.year} at "
        f"{hour}:{localized.strftime('%M %p %Z')}"
    )
