from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def taipei_date_str() -> str:
    return taipei_now().strftime("%Y-%m-%d")


def taipei_datetime_str() -> str:
    return taipei_now().strftime("%Y-%m-%d %H:%M:%S")
