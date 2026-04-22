import dateparser
from datetime import timedelta


def parse_datetime(text: str):
    dt = dateparser.parse(
        text,
        languages=["pl"],
        settings={
            "TIMEZONE": "Europe/Warsaw",
            "RETURN_AS_TIMEZONE_AWARE": False
        }
    )

    if not dt:
        raise ValueError(f"Cannot parse date: {text}")

    return dt


def build_event_time(date_hint: str, duration_minutes: int = 60):
    start = parse_datetime(date_hint)
    end = start + timedelta(minutes=duration_minutes)

    return start, end