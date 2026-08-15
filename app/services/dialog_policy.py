"""Deterministic dialog policy applied after semantic NLU.

The LLM is responsible for interpreting the user's meaning and extracting slots.
This module owns safety-critical dialog state decisions such as status selection
and high-confidence intent overrides for explicit commands.
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

WEEKDAY_ALIASES = {
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


def _normalized_text(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _canonicalize_date_hint(value):
    if value in (None, ""):
        return value
    text = _normalized_text(value)
    return WEEKDAY_ALIASES.get(text, text)


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


def _merged_create_event(current_state: dict | None, event: dict | None) -> dict:
    merged: dict = {}
    state = current_state or {}
    if state.get("operation") == "create":
        for key in ("title", "date_hint", "time_hint", "duration_minutes", "description"):
            value = state.get(key)
            if value not in (None, ""):
                merged[key] = value
    if isinstance(event, dict):
        for key, value in event.items():
            if value not in (None, ""):
                merged[key] = value
    return _sanitize_event(merged) or {}


def _create_is_complete(current_state: dict | None, event: dict | None) -> bool:
    merged = _merged_create_event(current_state, event)
    return bool(
        str(merged.get("title") or "").strip()
        and str(merged.get("date_hint") or "").strip()
        and _exact_time(merged.get("time_hint"))
        and _valid_duration(merged.get("duration_minutes"))
    )


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
    """Apply deterministic intent/status policy to structured LLM semantics."""
    result = copy.deepcopy(llm_result) if isinstance(llm_result, dict) else {}
    result.setdefault("reply", "")

    if isinstance(result.get("event"), dict):
        result["event"] = _sanitize_event(result["event"])
    if isinstance(result.get("search"), dict):
        result["search"] = _sanitize_search(result["search"])

    operation = infer_operation(message, result.get("operation"), current_state)
    result["operation"] = operation

    if operation == "cancelled":
        result["status"] = "cancelled"
    elif operation == "create":
        result["status"] = (
            "ready_for_confirmation"
            if _create_is_complete(current_state, result.get("event"))
            else "needs_input"
        )
    elif operation == "search":
        result["status"] = "calendar_search"
    elif operation == "delete":
        result["status"] = (
            "calendar_delete_confirmation"
            if _delete_has_target(current_state, result.get("search"))
            else "needs_input"
        )
    elif operation == "external_search":
        result["status"] = "external_search"
    else:
        result["operation"] = "chat"
        result["status"] = "chat"

    return result
