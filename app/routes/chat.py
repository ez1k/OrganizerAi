import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from google.auth.exceptions import RefreshError

from app.schemas import ChatRequest
from app.services.date_parser import build_event_time
from app.services.database import save_learning_example
from app.services.google_calendar import create_event, delete_event, search_events
from app.services.llm_service import ask_llm

logger = logging.getLogger(__name__)
router = APIRouter()
WARSAW = ZoneInfo("Europe/Warsaw")
WEEKDAYS_PL = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)
CONFIRMATION_RE = re.compile(
    r"^(?:ok\s+dodaj|okej\s+dodaj|no\s+dodaj|dawaj|dodawaj|tak|potwierdzam|potwierdź|dodaj|zapisz|jasne|zgadza się|zgadza sie|ok|okej|okay|yes)[.!\s]*$",
    re.I,
)
THANKS_RE = re.compile(
    r"^(?:dzięki|dzieki|dziękuję|dziekuje|super|super dzięki|super dzieki|ok dzięki|ok dzieki)[.!\s]*$",
    re.I,
)
ALL_DELETE_RE = re.compile(
    r"^\s*(?:usuń|usun|skasuj|wywal)\s+(?:je|oba|obie|wszystkie|wszystko|wszystkie te)\s*[.!]?\s*$",
    re.I,
)
CREATE_INTENT_RE = re.compile(
    r"\b(?:dodaj|dodać|dodac|zaplanuj|zaplanować|zaplanowac|umów|umow)\b",
    re.I,
)
CREATE_STATUS_RE = re.compile(
    r"\b(?:na\s+pewno\s+)?(?:dodałeś|dodales|dodałaś|dodalas|zapisałeś|zapisales)\b"
    r"|\bczy\s+(?:to\s+)?(?:jest|zostało|zostalo)\s+(?:już\s+)?(?:dodane|zapisane)\b"
    r"|\b(?:jest|zostało|zostalo)\s+(?:już\s+)?(?:dodane|zapisane)\b",
    re.I,
)
CREATE_MISSING_RE = re.compile(
    r"^\s*(?:jakich|czego\s+brakuje|jakie\s+dane|jakich\s+danych|co\s+brakuje|co\s+jeszcze)\s*[?.!]*\s*$",
    re.I,
)
DURATION_MINUTES_RE = re.compile(
    r"\b(\d{1,4})\s*(?:min|mins|minut|minuta|minuty|minutę)\b",
    re.I,
)
DURATION_HOURS_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(?:h|godz\.?|godzina|godziny|godzin|godzinę)\b",
    re.I,
)
CREATE_FIELD_LABELS = {
    "title": "tytułu",
    "date_hint": "dnia",
    "time_hint": "godziny rozpoczęcia",
    "duration_minutes": "czasu trwania",
}

GENERIC_CREATE_TITLES = {
    "wydarzenie",
    "event",
    "spotkanie",
    "do kalendarza wydarzenie",
    "do kalendarza event",
    "wydarzenie do kalendarza",
    "event do kalendarza",
}


def _is_confirmation(message):
    normalized = " ".join(message.strip().lower().split())
    return bool(
        CONFIRMATION_RE.fullmatch(normalized)
        or (normalized.startswith("tak") and "potwierdz" in normalized)
    )


def _is_thanks(message):
    return bool(THANKS_RE.fullmatch(" ".join(message.strip().lower().split())))


def _is_number_selection(message):
    match = re.fullmatch(r"\s*(\d+)\s*[.]?\s*", message)
    return int(match.group(1)) if match else None


def _is_delete_all(message):
    return bool(ALL_DELETE_RE.fullmatch(message))


def _is_calendar_search_intent(message):
    text = " ".join(str(message).strip().lower().split())
    patterns = (
        r"\bsprawdź\b",
        r"\bsprawdz\b",
        r"\bco\s+mam\b",
        r"\bjakie\s+mam\b",
        r"\bpokaż\b",
        r"\bpokaz\b",
        r"\bnajbliższe\s+wydarzenia\b",
        r"\bnajbliższych\s+(?:dwa|2)\s+tygodni",
        r"\bnajbliższe\s+(?:dwa|2)\s+tygodnie\b",
        r"\b(?:w|na)\s+tym\s+tygodniu\b",
        r"\b(?:na|w)\s+ten\s+tydzień\b",
        r"\bna\s+ten\s+tydzień\s+i\s+(?:następny|nastepny)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _merge_event(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint", "duration_minutes", "description"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged or None


def _merge_search(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint", "range_type", "range_days"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged


def _normalize_text(value):
    return " ".join(str(value or "").strip().lower().split())


def _normalize_create_title(value):
    text = _normalize_text(value).strip(" ,.;:!?-")
    text = re.sub(r"^(?:mi\s+)?do\s+(?:mojego\s+)?kalendarza\s+", "", text, flags=re.I)
    return text.strip(" ,.;:!?-")


def _is_generic_create_title(value):
    normalized = _normalize_create_title(value)
    return not normalized or normalized in GENERIC_CREATE_TITLES


def _extract_explicit_create_title(message):
    raw = str(message or "").strip()
    match = re.search(r"\b(?:tytuł|tytul)\s*[:=\-]\s*(.+)$", raw, re.I)
    if not match:
        return None
    candidate = match.group(1).strip(" ,.;:!?-")
    return candidate if candidate and not _is_generic_create_title(candidate) else None


def _extract_structured_continuation_title(message):
    """Extract a title from slot continuation such as 'środa 5:00, lot do bari - 90 min'."""
    raw = str(message or "").strip()
    if "," not in raw:
        return None

    tail = raw.split(",", 1)[1].strip()
    tail = DURATION_MINUTES_RE.sub(" ", tail)
    tail = DURATION_HOURS_RE.sub(" ", tail)
    tail = re.sub(r"\b(?:półtorej|poltorej|pół|pol)\s+godzin\w*\b", " ", tail, flags=re.I)
    tail = re.sub(r"\bkwadrans\b", " ", tail, flags=re.I)
    candidate = tail.strip(" ,.;:!?-–—")
    if not candidate or not re.search(r"[^\W\d_]", candidate, re.UNICODE):
        return None
    return candidate if not _is_generic_create_title(candidate) else None


def _extract_duration_minutes(message):
    text = _normalize_text(message)
    if not text:
        return None

    if re.search(r"\b(?:półtorej|poltorej)\s+godzin", text):
        return 90
    if re.search(r"\b(?:pół|pol)\s+godzin", text):
        return 30
    if re.search(r"\bkwadrans\b", text):
        return 15
    if re.search(r"\bgodzinę\b", text):
        return 60

    minutes_match = DURATION_MINUTES_RE.search(text)
    if minutes_match:
        minutes = int(minutes_match.group(1))
        return minutes if 0 < minutes <= 1440 else None

    hours_match = DURATION_HOURS_RE.search(text)
    if hours_match:
        hours = float(hours_match.group(1).replace(",", "."))
        minutes = round(hours * 60)
        return minutes if 0 < minutes <= 1440 else None

    return None


def _extract_create_date(message):
    text = _normalize_text(message)
    if not text:
        return None

    explicit = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\b", text)
    if explicit:
        day = int(explicit.group(1))
        month = int(explicit.group(2))
        if explicit.group(3):
            year = int(explicit.group(3))
        else:
            today = datetime.now(WARSAW).date()
            year = today.year
            try:
                candidate = datetime(year, month, day).date()
            except ValueError:
                return None
            if candidate < today:
                year += 1
        try:
            datetime(year, month, day)
        except ValueError:
            return None
        return f"{day:02d}.{month:02d}.{year:04d}"

    relative = re.search(r"\b(dzisiaj|dziś|jutro|pojutrze)\b", text)
    if relative:
        return relative.group(1).lower()

    weekday = re.search(
        r"\b(poniedziałek|poniedzialek|wtorek|środę|środa|srodę|srode|sroda|"
        r"czwartek|piątek|piatek|sobotę|sobote|sobota|niedzielę|niedziele|niedziela)\b",
        text,
        re.I,
    )
    if weekday:
        value = weekday.group(1).lower()
        aliases = {
            "poniedzialek": "poniedziałek",
            "środę": "środa",
            "srodę": "środa",
            "srode": "środa",
            "sroda": "środa",
            "piatek": "piątek",
            "sobotę": "sobota",
            "sobote": "sobota",
            "niedzielę": "niedziela",
            "niedziele": "niedziela",
        }
        return aliases.get(value, value)

    return None


def _extract_create_time(message):
    text = _normalize_text(message)
    if not text:
        return None

    working = DURATION_MINUTES_RE.sub(" ", text)
    working = DURATION_HOURS_RE.sub(" ", working)
    working = re.sub(r"\b(?:półtorej|poltorej|pół|pol)\s+godzin\w*\b", " ", working)
    working = re.sub(r"\bkwadrans\b", " ", working)

    explicit = re.search(r"\bo\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b", working)
    if explicit:
        return f"{int(explicit.group(1)):02d}:{int(explicit.group(2) or 0):02d}"

    colon_time = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", working)
    if colon_time:
        return f"{int(colon_time.group(1)):02d}:{int(colon_time.group(2)):02d}"

    day_then_time = re.search(
        r"\b(?:dzisiaj|dziś|jutro|pojutrze|poniedziałek|poniedzialek|wtorek|"
        r"środę|środa|srodę|srode|sroda|czwartek|piątek|piatek|sobotę|sobote|"
        r"sobota|niedzielę|niedziele|niedziela)\b"
        r"(?:\s+o)?\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b",
        working,
        re.I,
    )
    if day_then_time:
        return f"{int(day_then_time.group(1)):02d}:{int(day_then_time.group(2) or 0):02d}"

    bare = re.search(r"(?:^|\s)([01]?\d|2[0-3])\s*$", working)
    if bare:
        return f"{int(bare.group(1)):02d}:00"

    return None


def _extract_create_title(message, continuation=False):
    raw = str(message or "").strip()
    if not raw:
        return None

    explicit_title = _extract_explicit_create_title(raw)
    if explicit_title:
        return explicit_title

    if continuation:
        structured_title = _extract_structured_continuation_title(raw)
        if structured_title:
            return structured_title

    intent = re.search(
        r"\b(?:dodaj|dodać|dodac|zaplanuj|zaplanować|zaplanowac|umów|umow)\s+(.+)$",
        raw,
        re.I,
    )
    if intent:
        candidate = intent.group(1)
        candidate = re.split(
            r"\s+(?:na|w)?\s*(?:dzisiaj|dziś|jutro|pojutrze|poniedziałek|poniedzialek|"
            r"wtorek|środę|środa|srodę|srode|sroda|czwartek|piątek|piatek|"
            r"sobotę|sobote|sobota|niedzielę|niedziele|niedziela)\b",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]
        candidate = re.split(
            r"\s+\d{1,2}[./-]\d{1,2}(?:[./-]\d{4})?\b",
            candidate,
            maxsplit=1,
        )[0]
        candidate = re.split(
            r"\s+o\s+\d{1,2}(?::\d{2})?\b",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]
        candidate = candidate.strip(" ,.;:!?-")
        candidate = re.sub(
            r"^(?:mi\s+)?do\s+(?:mojego\s+)?kalendarza\s+",
            "",
            candidate,
            flags=re.I,
        ).strip(" ,.;:!?-")
        if candidate and not _is_generic_create_title(candidate):
            return candidate

    if continuation:
        duration_match = DURATION_MINUTES_RE.search(raw) or DURATION_HOURS_RE.search(raw)
        if duration_match:
            ignored = {
                "niech trwa",
                "ma trwać",
                "ma trwac",
                "trwa",
                "przez",
                "czas trwania",
                "proszę",
                "prosze",
                "dzięki",
                "dzieki",
                "ok",
                "okej",
            }
            prefix = raw[: duration_match.start()].strip(" ,.;:-")
            if (
                prefix
                and _normalize_text(prefix) not in ignored
                and not _is_generic_create_title(prefix)
            ):
                return prefix

            suffix = raw[duration_match.end() :].strip(" ,.;:-")
            suffix = re.sub(r"^(?:i|to|czyli)\s+", "", suffix, flags=re.I).strip(" ,.;:-")
            if (
                suffix
                and _normalize_text(suffix) not in ignored
                and not _is_generic_create_title(suffix)
            ):
                return suffix

    return None


def _extract_create_fields(message, continuation=False):
    fields = {}

    title = _extract_create_title(message, continuation=continuation)
    if title:
        fields["title"] = title

    date_hint = _extract_create_date(message)
    if date_hint:
        fields["date_hint"] = date_hint

    time_hint = _extract_create_time(message)
    if time_hint:
        fields["time_hint"] = time_hint

    duration = _extract_duration_minutes(message)
    if duration is not None:
        fields["duration_minutes"] = duration

    return fields


def _candidate_title_is_grounded(message, title):
    normalized_title = _normalize_create_title(title)
    return bool(
        normalized_title
        and not _is_generic_create_title(normalized_title)
        and normalized_title in _normalize_text(message)
    )


def _sanitize_create_event(message, state, candidate):
    """Merge CREATE data while blocking LLM-invented date/time/duration values."""
    current = dict(state or {}) if (state or {}).get("operation") == "create" else {}
    result = {
        key: value
        for key, value in current.items()
        if key
        in {
            "title",
            "date_hint",
            "time_hint",
            "duration_minutes",
            "description",
            "allow_duplicate",
            "duplicate_event",
        }
    }

    candidate = candidate if isinstance(candidate, dict) else {}
    candidate_title = candidate.get("title")
    if candidate_title not in (None, "") and _candidate_title_is_grounded(message, candidate_title):
        result["title"] = str(candidate_title).strip()

    candidate_description = candidate.get("description")
    if candidate_description not in (None, ""):
        result["description"] = str(candidate_description).strip()

    result.update(_extract_create_fields(message, continuation=bool(current)))
    result["operation"] = "create"
    return result


def _missing_event(event):
    missing = []
    for key in ("title", "date_hint", "time_hint"):
        if not event or not str(event.get(key, "")).strip():
            missing.append(key)

    duration = event.get("duration_minutes") if event else None
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        missing.append("duration_minutes")

    return missing


def _create_missing_message(event, missing=None):
    missing = missing or _missing_event(event)
    labels = ", ".join(CREATE_FIELD_LABELS[key] for key in missing)
    questions = {
        "title": "Jak ma się nazywać wydarzenie?",
        "date_hint": "Na jaki dzień mam je zaplanować?",
        "time_hint": "O której godzinie ma się rozpocząć?",
        "duration_minutes": "Ile ma trwać wydarzenie?",
    }
    first = missing[0] if missing else None
    if not first:
        return _create_confirmation_message(event)
    if len(missing) == 1:
        return f"Brakuje {labels}. {questions[first]}"
    return f"Brakuje jeszcze: {labels}. {questions[first]}"


def _build_event(data):
    title = str(data.get("title", "")).strip()
    date_hint = str(data.get("date_hint", "")).strip()
    time_hint = str(data.get("time_hint", "")).strip()
    try:
        duration = int(data.get("duration_minutes"))
    except (TypeError, ValueError):
        duration = 0

    if not title or not date_hint or not time_hint or duration <= 0:
        raise ValueError(
            "Wydarzenie nie jest kompletne: potrzebne są tytuł, dzień, godzina i czas trwania."
        )

    start, end = build_event_time(f"{date_hint} o {time_hint}", duration)
    if start.tzinfo is None:
        start = start.replace(tzinfo=WARSAW)
    else:
        start = start.astimezone(WARSAW)
    if end.tzinfo is None:
        end = end.replace(tzinfo=WARSAW)
    else:
        end = end.astimezone(WARSAW)

    return {
        "title": title,
        "description": str(data.get("description", "")).strip(),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _create_confirmation_message(event):
    built = _build_event(event)
    start = datetime.fromisoformat(built["start"]).astimezone(WARSAW)
    end = datetime.fromisoformat(built["end"]).astimezone(WARSAW)
    duration = int(event["duration_minutes"])
    return (
        "Podsumowanie wydarzenia:\n"
        f"• {built['title']}\n"
        f"• {WEEKDAYS_PL[start.weekday()]}, {start:%d.%m.%Y}\n"
        f"• {start:%H:%M}–{end:%H:%M} ({duration} min)\n\n"
        "Czy mam dodać to wydarzenie do Google Calendar?"
    )


def _asks_if_create_was_committed(message):
    return bool(CREATE_STATUS_RE.search(str(message or "")))


def _asks_for_missing_create_data(message):
    return bool(CREATE_MISSING_RE.fullmatch(str(message or "")))


def _extract_search_criteria(message, criteria):
    text = " ".join(str(message).strip().lower().split())
    result = dict(criteria or {})
    multi_week = re.search(
        r"\bnajbliższe\s+(?:dwa|2)\s+tygodnie\b"
        r"|\bnajbliższych\s+(?:dwa|2|dwóch)\s+tygodni(?:e|ach)?\b"
        r"|\bw\s+najbliższych\s+(?:dwa|2|dwóch)\s+tygodni(?:e|ach)?\b"
        r"|\bnajbliższe\s+14\s+dni\b"
        r"|\bprzez\s+najbliższe\s+(?:dwa|2|dwóch)\s+tygodnie\b"
        r"|\b(?:na|w)\s+ten\s+tydzień\s+i\s+(?:następny|nastepny)\b",
        text,
    )
    if multi_week:
        result["range_type"], result["range_days"] = "next_days", 14
        result.pop("date_hint", None)
        result.pop("time_hint", None)
    elif re.search(
        r"\bnajbliższe\s+(?:wydarzenia|dni)\b|\bnajbliższych\s+wydarze(?:ń|nia)\b",
        text,
    ):
        result["range_type"], result["range_days"] = "next_days", 14
        result.pop("date_hint", None)
        result.pop("time_hint", None)
    elif re.search(r"\b(?:w|na)\s+tym\s+tygodniu\b", text):
        result["range_type"] = "this_week"
        result.pop("date_hint", None)
        result.pop("time_hint", None)

    explicit_date = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\b", text)
    if explicit_date:
        day, month = int(explicit_date.group(1)), int(explicit_date.group(2))
        year = int(explicit_date.group(3)) if explicit_date.group(3) else datetime.now(WARSAW).year
        result["date_hint"] = f"{day:02d}.{month:02d}.{year:04d}"
        result.pop("range_type", None)
        result.pop("range_days", None)

    day_patterns = [
        r"\b(?:w|z|na)\s+(poniedziałek|poniedzialek|wtorek|środę|srodę|srode|czwartek|piątek|piatek|sobotę|sobote|niedzielę|niedziele)\b",
        r"\b(poniedziałek|poniedzialek|wtorek|środa|sroda|czwartek|piątek|piatek|sobota|niedziela)\b",
        r"\b(dzisiaj|dziś|jutro|pojutrze)\b",
    ]
    for pattern in day_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            day = {
                "środę": "środa",
                "srodę": "środa",
                "srode": "środa",
                "sobotę": "sobota",
                "sobote": "sobota",
                "niedzielę": "niedziela",
                "niedziele": "niedziela",
            }.get(match.group(1), match.group(1))
            result["date_hint"] = day
            result.pop("range_type", None)
            result.pop("range_days", None)
            break

    time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not time_match:
        time_match = re.search(r"\bo\s+(\d{1,2})(?:\s*(?:godz(?:ina|iny|in)?|h))?\b", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = (
            int(time_match.group(2) or 0)
            if time_match.lastindex and time_match.lastindex >= 2
            else 0
        )
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            result["time_hint"] = f"{hour:02d}:{minute:02d}"

    title_match = re.search(
        r"(?:usuń|usun|skasuj|wywal)\s+(.+?)(?=\s+(?:z|ze|w|we|o)\s+|$)",
        text,
        re.I,
    )
    if title_match and not result.get("title"):
        title = title_match.group(1).strip(" .,!?-")
        if title and title not in {"je", "oba", "obie", "wszystkie", "wszystko"}:
            result["title"] = title
    return result


def _day_range(date_hint):
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", date_hint):
        day, month, year = map(int, date_hint.split("."))
        start = datetime(year, month, day, tzinfo=WARSAW)
    else:
        start, _ = build_event_time(f"{date_hint} o 00:00", 1)
        if start.tzinfo is None:
            start = start.replace(tzinfo=WARSAW)
        else:
            start = start.astimezone(WARSAW)
    return start, start + timedelta(days=1)


def _normalize_time_hint(value):
    if not value:
        return None
    text = re.sub(r"^o\s*", "", str(value).strip().lower().replace(".", ":"))
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
    if not match:
        return text
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Nieprawidłowa godzina wydarzenia.")
    return f"{hour:02d}:{minute:02d}"


def _normalize_search_criteria(criteria):
    normalized = dict(criteria or {})
    normalized["title"] = str(normalized.get("title", "")).strip() or None
    normalized["date_hint"] = str(normalized.get("date_hint", "")).strip() or None
    normalized["time_hint"] = _normalize_time_hint(normalized.get("time_hint"))
    return normalized


def _search_range(criteria):
    now = datetime.now(WARSAW)
    if criteria.get("range_type") == "next_days":
        return now, now + timedelta(days=int(criteria.get("range_days") or 14))
    if criteria.get("range_type") == "this_week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start, start + timedelta(days=7)
    return None


def _search_calendar(criteria):
    criteria = _normalize_search_criteria(criteria)
    title, date_hint, time_hint = criteria["title"], criteria["date_hint"], criteria["time_hint"]
    range_window = _search_range(criteria)
    if range_window:
        start, end = range_window
        events = search_events(title=title, start=start, end=end, max_results=100)
        if time_hint:
            target = int(time_hint[:2]) * 60 + int(time_hint[3:])
            filtered = []
            for event in events:
                value = event.get("start", "")
                match = re.search(r"T(\d{2}):(\d{2})", value)
                if match and abs((int(match.group(1)) * 60 + int(match.group(2))) - target) <= 2:
                    filtered.append(event)
            return filtered
        return events
    if not date_hint:
        start, end = _search_range({"range_type": "next_days", "range_days": 14})
        return search_events(title=title, start=start, end=end, max_results=100)
    day_start, day_end = _day_range(date_hint)
    if not time_hint:
        return search_events(title=title, start=day_start, end=day_end, max_results=100)
    target = day_start.replace(
        hour=int(time_hint[:2]),
        minute=int(time_hint[3:]),
        second=0,
        microsecond=0,
    )
    return search_events(
        title=title,
        start=target - timedelta(minutes=2),
        end=target + timedelta(minutes=2),
        max_results=100,
    )


def _calendar_event_datetime(value):
    """Parse a Google Calendar date/dateTime value and convert it to Warsaw time."""
    if not value:
        return None, False
    text = str(value)
    all_day = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, all_day
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=WARSAW)
    else:
        parsed = parsed.astimezone(WARSAW)
    return parsed, all_day


def _event_count_label(count):
    if count == 1:
        return "wydarzenie"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "wydarzenia"
    return "wydarzeń"


def _format_event_line(index, event):
    title = str(event.get("title") or "Bez nazwy")
    start, all_day = _calendar_event_datetime(event.get("start"))
    end, _ = _calendar_event_datetime(event.get("end"))

    if not start:
        return f"{index}. {title} — {event.get('start', '?')} – {event.get('end', '?')}"

    date_label = f"{WEEKDAYS_PL[start.weekday()]}, {start:%d.%m.%Y}"
    if all_day:
        return f"{index}. {title} — {date_label} (cały dzień)"
    if end and end.date() == start.date():
        return f"{index}. {title} — {date_label}, {start:%H:%M}–{end:%H:%M}"
    if end:
        end_label = f"{WEEKDAYS_PL[end.weekday()]}, {end:%d.%m.%Y}, {end:%H:%M}"
        return f"{index}. {title} — {date_label}, {start:%H:%M} – {end_label}"
    return f"{index}. {title} — {date_label}, {start:%H:%M}"


def _format_events(events):
    """Render machine-oriented calendar values as concise Polish chat text."""
    if not events:
        return "Nie znalazłem żadnych wydarzeń."
    count = len(events)
    header = f"Znalazłem {count} {_event_count_label(count)}:"
    return header + "\n" + "\n".join(
        _format_event_line(i, event) for i, event in enumerate(events, 1)
    )


class CalendarAuthRequired(Exception):
    pass


def _calendar_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (FileNotFoundError, RefreshError) as exc:
        raise CalendarAuthRequired(str(exc)) from exc


def _last_matches(state):
    matches = state.get("matches") if isinstance(state, dict) else None
    return matches if isinstance(matches, list) else []


def _save_learning(request, result):
    try:
        save_learning_example(request.user_id, request.message, result, corrected=False)
    except Exception:
        logger.exception("Failed to save learning example for user_id=%s", request.user_id)


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    try:
        state = request.draft_event or {}
        selection = _is_number_selection(request.message)
        if selection is not None and _last_matches(state):
            matches = _last_matches(state)
            if 1 <= selection <= len(matches):
                selected = matches[selection - 1]
                if state.get("operation") == "delete":
                    return {
                        "status": "calendar_delete_confirmation",
                        "message": f"Wybrano „{selected['title']}”. Czy chcesz je usunąć?",
                        "event": {
                            **state,
                            "matches": [selected],
                            "selected_event_id": selected.get("id"),
                        },
                    }
                return {
                    "status": "calendar_search",
                    "message": _format_events([selected]),
                    "event": state,
                }

        if state.get("operation") == "delete" and state.get("matches") and _is_delete_all(request.message):
            return {
                "status": "calendar_delete_confirmation",
                "message": f"Znalazłem {len(state['matches'])} wydarzeń. Czy chcesz usunąć wszystkie?",
                "event": {**state, "delete_all": True},
            }
        if state.get("operation") == "delete" and state.get("delete_all") and _is_confirmation(request.message):
            for event in state.get("matches", []):
                _calendar_call(delete_event, event["id"])
            return {
                "status": "deleted",
                "message": f"Usunięte: {len(state.get('matches', []))} wydarzeń.",
                "event": None,
            }
        if state.get("operation") == "delete" and state.get("matches") and _is_confirmation(request.message):
            matches = state["matches"]
            if len(matches) != 1:
                return {
                    "status": "calendar_delete_confirmation",
                    "message": "Znalazłem więcej niż jedno pasujące wydarzenie. Wskaż numer, które usunąć.",
                    "event": state,
                }
            _calendar_call(delete_event, matches[0]["id"])
            return {
                "status": "deleted",
                "message": f"Usunięte: {matches[0]['title']}.",
                "event": None,
            }

        if state.get("operation") == "create":
            if _asks_if_create_was_committed(request.message):
                missing = _missing_event(state)
                suffix = (
                    f" {_create_missing_message(state, missing)}"
                    if missing
                    else " Czekam na Twoje potwierdzenie podsumowania."
                )
                return {
                    "status": "needs_input" if missing else "ready_for_confirmation",
                    "message": "Nie. To wydarzenie nie zostało jeszcze dodane do Google Calendar." + suffix,
                    "event": state,
                }

            if _asks_for_missing_create_data(request.message):
                missing = _missing_event(state)
                return {
                    "status": "needs_input" if missing else "ready_for_confirmation",
                    "message": _create_missing_message(state, missing),
                    "event": state,
                }

            if _is_confirmation(request.message):
                missing = _missing_event(state)
                if missing:
                    return {
                        "status": "needs_input",
                        "message": _create_missing_message(state, missing),
                        "event": state,
                    }

                event = _build_event(state)
                logger.warning(
                    "CALENDAR CREATE request title=%r start=%s end=%s duration_minutes=%s allow_duplicate=%s",
                    event["title"],
                    event["start"],
                    event["end"],
                    state.get("duration_minutes"),
                    bool(state.get("allow_duplicate")),
                )
                result = _calendar_call(
                    create_event,
                    event,
                    allow_duplicate=bool(state.get("allow_duplicate")),
                )
                duplicate = result.get("duplicate") if isinstance(result, dict) else None
                if duplicate and not state.get("allow_duplicate"):
                    return {
                        "status": "calendar_duplicate_confirmation",
                        "message": (
                            f"Takie wydarzenie już istnieje: „{duplicate['title']}” "
                            f"o {duplicate.get('start', '?')}. Czy chcesz mimo to dodać kolejne?"
                        ),
                        "event": {
                            **state,
                            "allow_duplicate": True,
                            "duplicate_event": duplicate,
                        },
                    }

                logger.warning(
                    "CALENDAR CREATE success title=%r start=%s end=%s",
                    event["title"],
                    event["start"],
                    event["end"],
                )
                _save_learning(request, {"operation": "create", "event": state})
                return {
                    "status": "confirmed",
                    "message": (
                        f"Dodane do Google Calendar: {event['title']} — "
                        f"{datetime.fromisoformat(event['start']).astimezone(WARSAW):%d.%m.%Y, %H:%M}"
                        f"–{datetime.fromisoformat(event['end']).astimezone(WARSAW):%H:%M}."
                    ),
                    "event": event,
                    "calendar_link": result.get("calendar_link") if isinstance(result, dict) else result,
                }

            if _is_thanks(request.message):
                return {"status": "chat", "message": "Nie ma za co!", "event": None}

        if _is_calendar_search_intent(request.message):
            previous_search = (
                state.get("search") if state.get("operation") in {"search", "delete"} else None
            )
            criteria = _normalize_search_criteria(
                _extract_search_criteria(request.message, previous_search)
            )
            events = _calendar_call(_search_calendar, criteria)
            _save_learning(request, {"operation": "search", "search": criteria})
            return {
                "status": "calendar_search",
                "message": _format_events(events),
                "event": {"operation": "search", "search": criteria, "matches": events},
            }

        history = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in request.history
        ]
        result = ask_llm(
            message=request.message,
            history=history,
            draft_event=request.draft_event,
            user_id=request.user_id,
        )
        operation = result.get("operation", "chat")
        status = result.get("status", "chat")
        reply = result.get("reply", "")

        if CREATE_INTENT_RE.search(request.message):
            operation = "create"

        if operation == "external_search":
            return {
                "status": "external_search",
                "message": (
                    "To pytanie wymaga aktualnych danych zewnętrznych. "
                    "Nie mam jeszcze podłączonego wyszukiwania internetowego, więc nie będę zgadywać odpowiedzi."
                ),
                "event": None,
            }
        if operation == "search":
            previous_search = (
                state.get("search") if state.get("operation") in {"search", "delete"} else None
            )
            criteria = _normalize_search_criteria(
                _extract_search_criteria(
                    request.message,
                    _merge_search(previous_search, result.get("search")),
                )
            )
            events = _calendar_call(_search_calendar, criteria)
            _save_learning(request, {"operation": "search", "search": criteria})
            return {
                "status": "calendar_search",
                "message": _format_events(events),
                "event": {"operation": "search", "search": criteria, "matches": events},
            }
        if operation == "delete":
            previous_matches = _last_matches(state)
            previous_search = (
                state.get("search") if state.get("operation") in {"search", "delete"} else None
            )
            criteria = _normalize_search_criteria(
                _extract_search_criteria(
                    request.message,
                    _merge_search(previous_search, result.get("search")),
                )
            )
            events = (
                previous_matches
                if previous_matches and not any(criteria.values())
                else _calendar_call(_search_calendar, criteria)
            )
            if not events:
                return {
                    "status": "chat",
                    "message": "Nie znalazłem pasującego wydarzenia do usunięcia.",
                    "event": None,
                }
            if len(events) > 1:
                return {
                    "status": "calendar_delete_confirmation",
                    "message": (
                        _format_events(events)
                        + "\nKtóre wydarzenie mam usunąć? Podaj numer albo napisz „usuń oba/wszystkie”."
                    ),
                    "event": {"operation": "delete", "search": criteria, "matches": events},
                }
            event = events[0]
            return {
                "status": "calendar_delete_confirmation",
                "message": (
                    f"Znalazłem „{event['title']}” o {event.get('start', '?')}. "
                    "Czy chcesz je usunąć?"
                ),
                "event": {"operation": "delete", "search": criteria, "matches": [event]},
            }

        if (
            state.get("operation") == "create"
            and operation == "chat"
            and (
                isinstance(result.get("event"), dict)
                or _extract_create_fields(request.message, continuation=True)
            )
        ):
            operation = "create"

        if operation == "create":
            event_data = _sanitize_create_event(
                request.message,
                state,
                result.get("event"),
            )
            missing = _missing_event(event_data)
            if missing:
                return {
                    "status": "needs_input",
                    "message": _create_missing_message(event_data, missing),
                    "event": event_data,
                }
            return {
                "status": "ready_for_confirmation",
                "message": _create_confirmation_message(event_data),
                "event": event_data,
            }

        # A normal conversation must never create or mutate a Calendar draft.
        # Existing draft state remains owned by the caller/session and can be
        # explicitly resumed or cancelled on a later turn.
        if operation == "chat":
            return {"status": "chat", "message": reply, "event": None}

        event_data = _merge_event(
            request.draft_event if state.get("operation", "create") == "create" else None,
            result.get("event"),
        )
        return {"status": status, "message": reply, "event": event_data}
    except CalendarAuthRequired as exc:
        return {
            "status": "calendar_auth_required",
            "message": "Google Calendar wymaga ponownej autoryzacji. Stan operacji został zachowany.",
            "error": str(exc),
            "event": request.draft_event,
        }
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "needs_input",
            "message": str(exc),
            "event": request.draft_event,
        }
    except Exception as exc:
        logger.exception("Unhandled chat error")
        return {"status": "error", "message": str(exc), "event": request.draft_event}
