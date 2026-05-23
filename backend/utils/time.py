from datetime import datetime, timezone

def utc_ts() -> int:
    """UTC unix timestamp (seconds)."""
    return int(datetime.now(timezone.utc).timestamp())