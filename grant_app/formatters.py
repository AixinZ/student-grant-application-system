from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo


VANCOUVER_TIMEZONE = ZoneInfo("America/Vancouver")


def probability_percent(value: Decimal) -> str:
    return f"{value * Decimal('100'):.2f}%"


def cad_currency(value: Decimal) -> str:
    return f"${value:,.2f} CAD"


def vancouver_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)

    localized = value.astimezone(VANCOUVER_TIMEZONE)
    hour = localized.strftime("%I").lstrip("0") or "0"
    return (
        f"{localized.strftime('%B')} {localized.day}, {localized.year} at "
        f"{hour}:{localized.strftime('%M %p %Z')}"
    )
