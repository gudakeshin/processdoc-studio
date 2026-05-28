from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Return current time in IST as a naive datetime (for DB storage)."""
    return datetime.now(IST).replace(tzinfo=None)
