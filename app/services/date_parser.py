import re
from datetime import datetime, timedelta

import dateparser


_TIME_RE = re.compile(
    r"(?:^|\s)(?:o\s*)?(\d{1,2})(?::|\.)?(\d{2})?(?:\s*(?:am|pm))?(?:\s|$)",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(
    r"(?:^|\s)(?:o\s*)?([01]?\d|2[0-3])(?::|\.)([0-5]\d)(?:\s|$)",
    re.IGNORECASE,
)
_DAY_RE = re.compile(
    r"\b(?:dzisiaj|dziś|jutro|pojutrze|poniedziałek|poniedzialek|wtorek|środa|sroda|czwartek|piątek|piatek|sobota|niedziela|w\s+(?:poniedziałek|poniedzialek|wtorek|środę|srode|czwartek|piątek|piatek|sobotę|sobote|niedzielę|niedziele))\b",
    re.IGNORECASE,
)
_DMY_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def _has_time(text: str) -> bool:
    return bool(_TIME_RE.search(text))


def _has_day(text: str) -> bool:
    return bool(_DAY_RE.search(text) or _DMY_DATE_RE.search(text) or _ISO_DATE_RE.search(text))


def _explicit_datetime(text: str):
    """Parse explicit numeric dates without depending on dateparser heuristics."""
    time_match = _CLOCK_RE.search(text)
    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))

    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        year = int(iso_match.group(1))
        month = int(iso_match.group(2))
        day = int(iso_match.group(3))
        try:
            return datetime(year, month, day, hour, minute)
        except ValueError as exc:
            raise ValueError(f"Nie można rozpoznać daty: {text}") from exc

    dmy_match = _DMY_DATE_RE.search(text)
    if not dmy_match:
        return None

    day = int(dmy_match.group(1))
    month = int(dmy_match.group(2))
    explicit_year = dmy_match.group(3)
    year = int(explicit_year) if explicit_year else datetime.now().year

    try:
        candidate = datetime(year, month, day, hour, minute)
    except ValueError as exc:
        raise ValueError(f"Nie można rozpoznać daty: {text}") from exc

    if not explicit_year and candidate.date() < datetime.now().date():
        try:
            candidate = candidate.replace(year=year + 1)
        except ValueError as exc:
            raise ValueError(f"Nie można rozpoznać daty: {text}") from exc
    return candidate


def parse_datetime(text: str):
    text = str(text or "").strip()
    if not text:
        raise ValueError("Brakuje dnia i godziny wydarzenia")

    if not _has_day(text):
        raise ValueError("Brakuje dnia wydarzenia")

    if not _has_time(text):
        raise ValueError("Brakuje godziny wydarzenia")

    explicit = _explicit_datetime(text)
    if explicit is not None:
        return explicit

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
