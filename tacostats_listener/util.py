from datetime import datetime, timezone

def now() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())