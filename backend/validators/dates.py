"""Date validation: a real calendar date (ISO YYYY-MM-DD) that is not in the future."""
from datetime import date
from typing import Optional


def check_date(iso_value: str, today: Optional[date] = None) -> Optional[str]:
    """Return a reason code, or None when the date is valid."""
    try:
        d = date.fromisoformat(iso_value)
    except (TypeError, ValueError):
        return "invalid_date"
    if d > (today or date.today()):
        return "future_date"
    if d.year < 2000:
        return "invalid_date"
    return None
