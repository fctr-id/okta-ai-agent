"""Parse provider retry hints without exposing response headers or bodies."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


def retry_after_seconds(headers):
    value = headers.get('retry-after')
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            try:
                seconds = float(headers.get('retry-after-ms')) / 1000
            except (TypeError, ValueError):
                return None
    return math.ceil(max(0, seconds)) if math.isfinite(seconds) and seconds <= 86400 else None
