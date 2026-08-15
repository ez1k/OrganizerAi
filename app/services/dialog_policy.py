"""Deterministic dialog policy applied after semantic NLU.

The LLM is responsible for interpreting the user's meaning and extracting slots.
This module owns safety-critical dialog state decisions, high-confidence intent
overrides, and grounding of safety-sensitive slots before they reach runtime.
"""

from __future__ import annotations

import copy
import re

VALID_OPERATIONS = {
    "create",
    "search",
    "delete",
    "external_search",
    "chat",
    "cancelled",
}

CREATE_INTENT_RE = re.compile(
    r"\b(?:dodaj|dodać|dodac|zaplanuj|zaplanować|zaplanowac|umów|umow|wpisz|wrzuć|wrzuc)\b",
    re.I,
)
SEARCH_INTENT_RE = re.compile(
    r"\b(?:sprawdź|sprawdz|pokaż|pokaz)\b"
    r"|\bco\s+(?:ja\s+)?(?:właściwie\s+)?mam\b"
    r"|\bczy\s+mam\b"
    r"|\bjak\s+wygląda\s+(?:mój|moj)\s+kalendarz\b",
    re.I,
)
DELETE_INTENT_RE = re.compile(r"\b(?:usuń|usun|skasuj|wywal)\b", re.I)
EXTERNAL_INTENT_RE = re.compile(
    r"\b(?:pogoda|pogodę|pogode|kino|kinie|film|filmy|repertuar|wiadomości|wiadomosci|kurs\s+walut)\b",
    re.I,
)
CANCEL_INTENT_RE = re.compile(
    r"\b(?:nieważne|niewazne|anuluj|odpuść|odpusc|zrezygnuj)\b",
    re.I,
)
CHAT_ONLY_RE = re.compile(
    r"^\s*(?:hej|cześć|czesc|siema)(?:\s*[,!.?]?\s*(?:co\s+tam|jak\s+leci)\s*[!.?]*)?$",
    re.I,
)

VAGUE_TIME_RE = re.compile(
    r"^\s*(?:rano|przed\s+południem|przed\s+poludniem|po\s+południu|po\s+poludniu|wieczorem|w\s+nocy)\s*$",
    re.I,
)
EXACT_TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3])(?::[0-5]\d)?$")
DURATION_MINUTES_RE = re.compile(
    r"\b(\d{1,4})\s*(?:min|mins|minut|minuta|minuty|minutę)\b",
    re.I,
)
DURATION_HOURS_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(?:h|godz\.?|godzina|godziny|godzin|godzinę)\b",
    re.I,
)

WEEKDAY_ALIASES = {
    "poniedzialek": "poniedziałek",
    "poniedziałku": "poniedziałek",
    "poniedzialku": "poniedziałek",
    "wtorku": "wtorek",
    "środę": "środa",
    "srodę": "środa",
    "srode": "środa",
    "sroda": "środa",
    "środy": "środa",
    "srody": "środa",
    "czwartku": "czwartek",
    "piatek": "piątek",
    "piątku": "piątek",
    "piatku": "piątek",
    "sobotę": "sobota",
    "sobote": "sobota",
    "soboty": "sobota",
    "niedzielę": "niedziela",
    "niedziele": "niedziela",
    "niedzieli": "niedziela",
}
WEEKDAY_FORMS = tuple(
    dict.fromkeys(
        (
            "poniedziałek",
            "poniedzialek",
            "poniedziałku",
            "poniedzialku",
            "wtorek",
            "wtorku",
            "środa",
            "sroda",
            "środę",
            "srodę",
            "srode",
            "środy",
            "srody",
            "czwartek",
            "czwartku",
            "piątek",
            "piatek",
            "piątku",
            "piatku",
            "sobota",
            "sobotę",
            "sobote",
            "soboty",
            "niedziela",
            "niedzielę",
            "niedziele",
            "niedzieli",
        )
    )
)
GENERIC_DELETE_TITLES = {
    "wydarzenie",
    "to wydarzenie",
    "event",
    "ten event",
    "to",
    "ten",
    "ta",
    "go",
    "je",
    "ten drugi",
    "ten pierwszy",
}


def _normalized_text(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _canonicalize_date_hint(value):
    if value in (None, ""):
        return value
    text = _normalized_text(value)
    return WEEKDAY_ALIASES.get(text, text)


def _canonical_time(hour: int, minute: int = 0) -> str | None:
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def _extract_grounded_duration(message: str) -> int | None:
    text = _normalized_text(message)
    if not text:
        return None

    if re.search(r"\b(?:półtorej|poltorej)\s+godzin\w*\b", text):
        return 90
    if re.search(r"\b(?:pół|pol)\s+godzin\w*\b", text):
        return 30
    if re.search(r"\bkwadrans\b", text):
        return 15
    if re.search(r"\b(?:jedną\s+|jedna\s+)?godzinę\b|\bgodzine\b", text):
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

    word_hours = re.search(r"\b(dwie|dwa)\s+godzin\w*\b", text)
    if word_hours:
        return 120
    return None


def _without_duration_phrases(message: str) -> str:
    text = _normalized_text(message)
    text = DURATION_MINUTES_RE.sub(" ", text)
    text = DURATION_HOURS_RE.sub(" ", text)
    text = re.sub(
        r"\b(?:półtorej|poltorej|pół|pol|dwie|dwa)\s+godzin\w*\b",
        " ",
        text,
    )
    text = re.sub(r"\b(?:jedną\s+|jedna\s+)?godzinę\b|\bgodzine\b|\bkwadrans\b", " ", text)
    return " ".join(text.split())


def _extract_grounded_time(message: str) -> str | None:
    text = _without_duration_phrases(message)
    if not text:
        return None

    match = re.search(r"\bo\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b", text)
    if match:
        return _canonical_time(int(match.group(1)), int(match.group(2) or 0))

    match = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text)
    if match:
        return _canonical_time(int(match.group(1)), int(match.group(2)))

    return None


def _extract_grounded_date(message: str) -> str | None:
    text = _normalized_text(message)
    if not text:
        return None

    explicit = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\b", text)
    if explicit:
        day = int(explicit.group(1))
        month = int(explicit.group(2))
        year = explicit.group(3)
        if year:
            return f"{day:02d}.{month:02d}.{int(year):04d}"
        return f"{day:02d}.{month:02d}"

    relative = re.search(r"\b(dzisiaj|dziś|jutro|pojutrze)\b", text)
    if relative:
        return relative.group(1).lower()

    for form in sorted(WEEKDAY_FORMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(form)}\b", text, re.I):
            return _canonicalize_date_hint(form)
    return None


def _sanitize_event(event):
    if not isinstance(event, dict):
        return event

    sanitized = copy.deepcopy(event)
    if "date_hint" in sanitized:
        sanitized["date_hint"] = _canonicalize_date_hint(sanitized.get("date_hint"))

    time_hint = sanitized.get("time_hint")
    if isinstance(time_hint, str) and VAGUE_TIME_RE.fullmatch(time_hint):
        sanitized.pop("time_hint", None)

    return sanitized


def _sanitize_search(search):
    if not isinstance(search, dict):
        return search
    sanitized = copy.deepcopy(search)
    if "date_hint" in sanitized:
        sanitized["date_hint"] = _canonicalize_date_hint(sanitized.get("date_hint"))
    return sanitized


def infer_operation(message: str, llm_operation=None, current_state: dict | None = None) -> str:
    """Resolve operation using explicit lexical signals before the LLM guess.

    These overrides intentionally cover only high-confidence language. Ambiguous
    utterances continue to rely on the semantic NLU result.
    """
    text = str(message or "")
    state = current_state or {}

    if CANCEL_INTENT_RE.search(text) and state.get("operation") in {
        "create",
        "delete",
        "search",
    }:
        return "cancelled"
    if DELETE_INTENT_RE.search(text):
        return "delete"
    if CREATE_INTENT_RE.search(text):
        return "create"
    if EXTERNAL_INTENT_RE.search(text):
        return "external_search"
    if SEARCH_INTENT_RE.search(text):
        return "search"
    if CHAT_ONLY_RE.fullmatch(text):
        return "chat"

    normalized = _normalized_text(llm_operation)
    return normalized if normalized in VALID_OPERATIONS else "chat"


def _valid_duration(value) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _exact_time(value) -> bool:
    if value in (None, ""):
        return False
    text = _normalized_text(value).removeprefix("o ").replace(".", ":")
    if not EXACT_TIME_RE.fullmatch(text):
        return False
    if ":" not in text:
        return True
    hour, minute = map(int, text.split(":"))
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _state_create_event(current_state: dict | None) -> dict:
    state = current_state or {}
    if state.get("operation") != "create":
        return {}
    return {
        key: value
        for key in ("title", "date_hint", "time_hint", "duration_minutes", "description")
        if (value := state.get(key)) not in (None, "")
    }


def _ground_create_event(
    message: str,
    current_state: dict | None,
    event: dict | None,
) -> dict:
    """Keep semantic title/description but ground date/time/duration in user evidence.

    Existing CREATE state is trusted because it was already validated in earlier
    turns. New safety-sensitive values may only enter from the current message.
    """
    grounded = _state_create_event(current_state)
    candidate = _sanitize_event(event) if isinstance(event, dict) else {}

    for key in ("title", "description"):
        value = candidate.get(key) if isinstance(candidate, dict) else None
        if value not in (None, ""):
            grounded[key] = value

    date_hint = _extract_grounded_date(message)
    if date_hint:
        grounded["date_hint"] = date_hint

    time_hint = _extract_grounded_time(message)
    if time_hint:
        grounded["time_hint"] = time_hint

    duration = _extract_grounded_duration(message)
    if duration is not None:
        grounded["duration_minutes"] = duration

    return _sanitize_event(grounded) or {}


def _create_is_complete(event: dict | None) -> bool:
    event = event or {}
    return bool(
        str(event.get("title") or "").strip()
        and str(event.get("date_hint") or "").strip()
        and _exact_time(event.get("time_hint"))
        and _valid_duration(event.get("duration_minutes"))
    )


def _clean_delete_title(value) -> str | None:
    text = _normalized_text(value).strip(" ,.;:!?-")
    text = re.sub(r"^(?:mi|proszę|prosze)\s+", "", text).strip()
    if not text or text in GENERIC_DELETE_TITLES:
        return None
    return text


def _extract_delete_title(message: str) -> str | None:
    text = _normalized_text(message)
    match = DELETE_INTENT_RE.search(text)
    if not match:
        return None

    tail = text[match.end() :].strip(" ,.;:!?-")
    tail = re.sub(r"^(?:mi|proszę|prosze)\s+", "", tail).strip()
    if not tail:
        return None

    cut_patterns = [
        r"\s+(?:z|ze|w|we|na)\s+(?:" + "|".join(re.escape(v) for v in WEEKDAY_FORMS) + r")\b",
        r"\s+\b(?:dzisiaj|dziś|jutro|pojutrze)\b",
        r"\s+\d{1,2}[./-]\d{1,2}(?:[./-]\d{4})?\b",
        r"\s+o\s+(?:[01]?\d|2[0-3])(?::[0-5]\d)?\b",
    ]
    cut_at = len(tail)
    for pattern in cut_patterns:
        found = re.search(pattern, tail, re.I)
        if found:
            cut_at = min(cut_at, found.start())
    return _clean_delete_title(tail[:cut_at])


def _state_delete_search(current_state: dict | None) -> dict:
    state = current_state or {}
    if state.get("operation") != "delete" or not isinstance(state.get("search"), dict):
        return {}
    return _sanitize_search(state.get("search")) or {}


def _ground_delete_search(
    message: str,
    current_state: dict | None,
    search: dict | None,
) -> dict:
    grounded = _state_delete_search(current_state)

    title = _extract_delete_title(message)
    if title:
        grounded["title"] = title
    elif isinstance(search, dict):
        candidate_title = _clean_delete_title(search.get("title"))
        if candidate_title and candidate_title in _normalized_text(message):
            grounded["title"] = candidate_title

    date_hint = _extract_grounded_date(message)
    if date_hint:
        grounded["date_hint"] = date_hint

    time_hint = _extract_grounded_time(message)
    if time_hint:
        grounded["time_hint"] = time_hint

    return _sanitize_search(grounded) or {}


def _delete_has_target(current_state: dict | None, search: dict | None) -> bool:
    if isinstance(search, dict) and any(
        search.get(key) not in (None, "")
        for key in ("title", "date_hint", "time_hint", "range_type", "range_days")
    ):
        return True

    state = current_state or {}
    if state.get("operation") == "delete":
        state_search = state.get("search")
        if isinstance(state_search, dict) and any(value not in (None, "") for value in state_search.values()):
            return True
        if state.get("matches"):
            return True
    return False


def apply_dialog_policy(
    message: str,
    llm_result: dict | None,
    current_state: dict | None = None,
) -> dict:
    """Apply deterministic intent, grounding, and status policy to NLU output."""
    result = copy.deepcopy(llm_result) if isinstance(llm_result, dict) else {}
    result.setdefault("reply", "")

    operation = infer_operation(message, result.get("operation"), current_state)
    result["operation"] = operation

    if operation == "cancelled":
        result["status"] = "cancelled"
    elif operation == "create":
        grounded_event = _ground_create_event(message, current_state, result.get("event"))
        result["event"] = grounded_event
        result["status"] = (
            "ready_for_confirmation" if _create_is_complete(grounded_event) else "needs_input"
        )
    elif operation == "search":
        if isinstance(result.get("search"), dict):
            result["search"] = _sanitize_search(result["search"])
        result["status"] = "calendar_search"
    elif operation == "delete":
        grounded_search = _ground_delete_search(message, current_state, result.get("search"))
        if grounded_search:
            result["search"] = grounded_search
        else:
            result.pop("search", None)
        result["status"] = (
            "calendar_delete_confirmation"
            if _delete_has_target(current_state, grounded_search)
            else "needs_input"
        )
    elif operation == "external_search":
        result["status"] = "external_search"
    else:
        result["operation"] = "chat"
        result["status"] = "chat"

    return result
