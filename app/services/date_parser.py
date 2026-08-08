import re
from datetime import datetime, timedelta

import dateparser


_TIME_RE = re.compile(r"(?:^|\s)(?:o\s*)?(\d{1,2})(?::|\.)?(\d{2})?(?:\s*(?:am|pm))?(?:\s|$)", re.IGNORECASE)
_DAY_RE = re.compile(
    r"\b(?:dzisiaj|dziś|jutro|pojutrze|poniedziałek|poniedzialek|wtorek|środa|sroda|czwartek|piątek|piatek|sobota|niedziela|w\s+(?:poniedziałek|poniedzialek|wtorek|środę|srode|czwartek|piątek|piatek|sobotę|sobote|niedzielę|niedziele))\b",
    re.IGNORECASE,
)


def _has_time(text: str) -> bool:
    return bool(_TIME_RE.search(text))


def _has_day(text: str) -> bool:
    return bool(_DAY_RE.search(text))


def parse_datetime(text: str):
    text = str(text or "").strip()
    if not text:
        raise ValueError("Brakuje dnia i godziny wydarzenia")

    if not _has_day(text):
        raise ValueError("Brakuje dnia wydarzenia")

    if not _has_time(text):
        raise ValueError("Brakuje godziny wydarzenia")

    dt = dateparser.parse(
        text,
        languages=["pl"],
        settings={
            "TIMEZONE": "Europe/Warsaw",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
        },
    )

    if not dt:
        raise ValueError(f"Nie można rozpoznać daty: {text}")

    return dt


def build_event_time(date_hint: str, duration_minutes: int = 60):
    start = parse_datetime(date_hint)
    end = start + timedelta(minutes=duration_minutes)
    return start, end
