"""Calendar alignment for Indian district weather (Open-Meteo uses IST)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def india_today(now: datetime | None = None) -> date:
    """Return the IST date; injected instants must carry an explicit timezone."""
    if now is None:
        now = datetime.now(INDIA_TIMEZONE)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware datetime is required")
    return now.astimezone(INDIA_TIMEZONE).date()
