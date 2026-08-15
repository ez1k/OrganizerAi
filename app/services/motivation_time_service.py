"""Deterministic parsing of natural-language motivational reminder delays.

The parser intentionally accepts only high-confidence relative expressions. It
never guesses a vague phrase such as ``kiedyś``. A parsed reminder only schedules
a future notification; it never creates a Google Calendar event.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")

_NUMBER_WORDS = {
    "jeden": 1,
    "jedna": 1,
    "jedna": 1,
    "jedna": 1,
    "dwa": 2,
    "dwie": 2,
    "trzy": 3,
    "cztery": 4,
    "piec": 5,
    "szesc": 6,
    "siedem": 7,
    "osiem": 8,
    "dziewiec": 9,
    "dziesiec": 10,
    "jedenascie": 11,
    "dwanascie": 12,
}

_NUMBER_PATTERN = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))


def _ascii_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_marks.split())


def _number(value: str) -> int | None:
    token = _ascii_text(value)
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def parse_motivation_reminder_time(
    when_text: str,
    *,
    now: datetime | None = None,
) -> datetime:
    """Parse a precise relative reminder phrase into a Warsaw-aware datetime.

    Supported examples include ``za 2 minuty``, ``za godzinę``, ``jutro``,
    ``za dwa tygodnie`` and ``za miesiąc``. Vague requests are rejected so the
    caller can ask the user for a more precise delay.
    """
    text = _ascii_text(when_text)
    if not text:
        raise ValueError("Podaj, za jaki czas mam przypomnieć.")

    base = now or datetime.now(WARSAW)
    if base.tzinfo is None:
        base = base.replace(tzinfo=WARSAW)
    else:
        base = base.astimezone(WARSAW)

    if re.search(r"\bza\s+kwadrans\b", text):
        target = base + timedelta(minutes=15)
    elif re.search(r"\bza\s+pol\s+godziny\b", text):
        target = base + timedelta(minutes=30)
    elif re.search(r"\bjutro\b", text):
        target = base + timedelta(days=1)
    elif re.search(r"\bza\s+tydzien\b", text) or re.search(r"\bw\s+przyszlym\s+tygodniu\b", text):
        target = base + timedelta(days=7)
    elif re.search(r"\bza\s+miesiac\b", text):
        target = _add_months(base, 1)
    elif re.search(r"\bza\s+rok\b", text):
        target = _add_months(base, 12)
    else:
        match = re.search(
            rf"\bza\s+(\d+|{_NUMBER_PATTERN})\s+"
            r"(minut(?:e|y)?|godzin(?:e|y)?|dni|dzien|"
            r"tygodni(?:e)?|miesiac(?:e|y)?|miesiecy)\b",
            text,
        )
        if not match:
            raise ValueError(
                "Nie rozumiem terminu przypomnienia. Napisz np. „za 2 tygodnie”, "
                "„za miesiąc” albo „za 15 minut”."
            )

        amount = _number(match.group(1))
        if amount is None or amount <= 0:
            raise ValueError("Odstęp przypomnienia musi być dodatni.")

        unit = match.group(2)
        if unit.startswith("minut"):
            target = base + timedelta(minutes=amount)
        elif unit.startswith("godzin"):
            target = base + timedelta(hours=amount)
        elif unit in {"dzien", "dni"}:
            target = base + timedelta(days=amount)
        elif unit.startswith("tygodni"):
            target = base + timedelta(weeks=amount)
        else:
            target = _add_months(base, amount)

    if target <= base:
        raise ValueError("Termin przypomnienia musi być w przyszłości.")
    if target > _add_months(base, 60):
        raise ValueError("Termin przypomnienia jest zbyt odległy. Podaj maksymalnie 5 lat.")
    return target
