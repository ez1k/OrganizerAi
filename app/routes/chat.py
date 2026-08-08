import json
import re
from datetime import timedelta

from fastapi import APIRouter
from google.auth.exceptions import RefreshError

from app.services.date_parser import build_event_time
from app.services.google_calendar import create_event, delete_event, search_events
from app.services.llm_service import ask_llm
from app.schemas import ChatRequest

router = APIRouter()

CONFIRMATION_RE = re.compile(r"^(?:tak|tak,|potwierdzam|potwierdź|dodaj|zapisz|jasne|zgadza się|zgadza sie|ok|okej|okay|yes)[.!\s]*$", re.IGNORECASE)
ALL_DELETE_RE = re.compile(r"^\s*(?:usuń|usun|skasuj|wywal)\s+(?:je|oba|obie|wszystkie|wszystko|wszystkie te)\s*[.!]?\s*$", re.IGNORECASE)


def _is_confirmation(message: str) -> bool:
    normalized = " ".join(message.strip().lower().split())
    return bool(CONFIRMATION_RE.fullmatch(normalized) or (normalized.startswith("tak") and "potwierdz" in normalized))


def _is_number_selection(message: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*[.]?\s*", message)
    return int(match.group(1)) if match else None


def _is_delete_all(message: str) -> bool:
    return bool(ALL_DELETE_RE.fullmatch(message))


def _merge_event(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint", "duration_minutes", "description"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged or None


def _merge_search(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged


def _extract_search_criteria(message: str, criteria: dict) -> dict:
    """Deterministically recover common Polish day/time/title phrases for SEARCH/DELETE."""
    text = " ".join(str(message).strip().lower().split())
    result = dict(criteria or {})

    day_patterns = [
        r"\b(?:w|z)\s+(poniedziałek|poniedzialek|wtorek|środę|srodę|srode|czwartek|piątek|piatek|sobotę|sobote|niedzielę|niedziele)\b",
        r"\b(poniedziałek|poniedzialek|wtorek|środa|sroda|czwartek|piątek|piatek|sobota|niedziela)\b",
        r"\b(dzisiaj|dziś|jutro|pojutrze)\b",
    ]
    for pattern in day_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            day = match.group(1)
            day = {"środę": "środa", "srodę": "środa", "srode": "środa", "sobotę": "sobota", "sobote": "sobota", "niedzielę": "niedziela", "niedziele": "niedziela"}.get(day, day)
            result["date_hint"] = day
            break

    time_match = re.search(r"\b(?:o\s*)?(\d{1,2})(?::(\d{2}))?\s*(?:godz(?:ina|iny|in)?|h)?\b", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            result["time_hint"] = f"{hour:02d}:{minute:02d}"

    title_match = re.search(r"(?:usuń|usun|skasuj|wywal)\s+(.+?)(?=\s+(?:z|ze|w|we|o)\s+|$)", text, re.IGNORECASE)
    if title_match and not result.get("title"):
        title = title_match.group(1).strip(" .,!?-")
        if title and title not in {"je", "oba", "obie", "wszystkie", "wszystko"}:
            result["title"] = title

    return result


def _missing_event(event):
    return [key for key in ("title", "date_hint", "time_hint") if not event or not str(event.get(key, "")).strip()]


def _build_event(data):
    title = str(data.get("title", "")).strip()
    date_hint = str(data.get("date_hint", "")).strip()
    time_hint = str(data.get("time_hint", "")).strip()
    duration = int(data.get("duration_minutes") or 60)
    if not title or not date_hint or not time_hint:
        raise ValueError("Brakuje nazwy, dnia lub godziny wydarzenia.")
    start, end = build_event_time(f"{date_hint} o {time_hint}", duration)
    return {"title": title, "description": str(data.get("description", "")).strip(), "start": start.isoformat(), "end": end.isoformat()}


def _day_range(date_hint):
    start, _ = build_event_time(f"{date_hint} o 00:00", 1)
    return start, start + timedelta(days=1)


def _normalize_time_hint(value):
    if not value:
        return None
    text = str(value).strip().lower().replace(".", ":")
    text = re.sub(r"^o\s*", "", text)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
    if not match:
        return text
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Nieprawidłowa godzina wydarzenia.")
    return f"{hour:02d}:{minute:02d}"


def _normalize_search_criteria(criteria):
    normalized = dict(criteria or {})
    normalized["title"] = str(normalized.get("title", "")).strip() or None
    normalized["date_hint"] = str(normalized.get("date_hint", "")).strip() or None
    normalized["time_hint"] = _normalize_time_hint(normalized.get("time_hint"))
    return normalized


def _search_calendar(criteria):
    criteria = _normalize_search_criteria(criteria)
    title, date_hint, time_hint = criteria["title"], criteria["date_hint"], criteria["time_hint"]
    if not date_hint:
        return search_events(title=title, max_results=20)
    day_start, day_end = _day_range(date_hint)
    if not time_hint:
        return search_events(title=title, start=day_start, end=day_end, max_results=20)
    target, _ = build_event_time(f"{date_hint} o {time_hint}", 1)
    return search_events(title=title, start=target - timedelta(minutes=2), end=target + timedelta(minutes=2), max_results=20)


def _format_events(events):
    if not events:
        return "Nie znalazłem żadnych wydarzeń."
    return "Znalazłem:\n" + "\n".join(f"{i}. {e['title']} — {e.get('start', '?')} – {e.get('end', '?')}" for i, e in enumerate(events, 1))


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
                    return {"status": "calendar_delete_confirmation", "message": f"Wybrano „{selected['title']}”. Czy chcesz je usunąć?", "event": {**state, "matches": [selected], "selected_event_id": selected.get("id")}}
                return {"status": "calendar_search", "message": _format_events([selected]), "event": state}

        if state.get("operation") == "delete" and state.get("matches") and _is_delete_all(request.message):
            return {"status": "calendar_delete_confirmation", "message": f"Znalazłem {len(state['matches'])} wydarzeń. Czy chcesz usunąć wszystkie?", "event": {**state, "delete_all": True}}

        if state.get("operation") == "delete" and state.get("delete_all") and _is_confirmation(request.message):
            matches = state.get("matches", [])
            for event in matches:
                _calendar_call(delete_event, event["id"])
            return {"status": "deleted", "message": f"Usunięte: {len(matches)} wydarzeń.", "event": None}

        if state.get("operation") == "delete" and state.get("matches") and _is_confirmation(request.message):
            matches = state["matches"]
            if len(matches) != 1:
                return {"status": "calendar_delete_confirmation", "message": "Znalazłem więcej niż jedno pasujące wydarzenie. Wskaż numer, które usunąć.", "event": state}
            _calendar_call(delete_event, matches[0]["id"])
            return {"status": "deleted", "message": f"Usunięte: {matches[0]['title']}.", "event": None}

        if state.get("operation") == "create" and _is_confirmation(request.message):
            missing = _missing_event(state)
            if missing:
                return {"status": "needs_input", "message": "Brakuje jeszcze danych wydarzenia.", "event": state}
            event = _build_event(state)
            allow_duplicate = bool(state.get("allow_duplicate"))
            result = _calendar_call(create_event, event, allow_duplicate=allow_duplicate)
            duplicate = result.get("duplicate") if isinstance(result, dict) else None
            if duplicate and not allow_duplicate:
                return {"status": "calendar_duplicate_confirmation", "message": f"Takie wydarzenie już istnieje: „{duplicate['title']}” o {duplicate.get('start', '?')}. Czy chcesz mimo to dodać kolejne?", "event": {**state, "allow_duplicate": True, "duplicate_event": duplicate}}
            link = result.get("calendar_link") if isinstance(result, dict) else result
            return {"status": "confirmed", "message": f"Dodane: {event['title']}.", "event": event, "calendar_link": link}

        history = [item.model_dump() if hasattr(item, "model_dump") else item.dict() for item in request.history]
        result = ask_llm(message=request.message, history=history, draft_event=request.draft_event)
        operation, status, reply = result.get("operation", "chat"), result.get("status", "chat"), result.get("reply", "")

        if operation == "external_search":
            return {"status": "external_search", "message": "To pytanie dotyczy informacji spoza kalendarza. Nie mam jeszcze podłączonego wyszukiwania internetowego, więc nie będę zgadywać odpowiedzi.", "event": None}

        if operation == "search":
            criteria = _merge_search(state.get("search") if state.get("operation") == "search" else None, result.get("search"))
            criteria = _normalize_search_criteria(_extract_search_criteria(request.message, criteria))
            events = _calendar_call(_search_calendar, criteria)
            return {"status": "calendar_search", "message": _format_events(events), "event": {"operation": "search", "search": criteria, "matches": events}}

        if operation == "delete":
            previous_matches = _last_matches(state)
            criteria = _merge_search(state.get("search") if state.get("operation") in {"search", "delete"} else None, result.get("search"))
            criteria = _normalize_search_criteria(_extract_search_criteria(request.message, criteria))
            events = previous_matches if previous_matches and not any(criteria.values()) else _calendar_call(_search_calendar, criteria)
            if not events:
                return {"status": "chat", "message": "Nie znalazłem pasującego wydarzenia do usunięcia.", "event": None}
            if len(events) > 1:
                return {"status": "calendar_delete_confirmation", "message": _format_events(events) + "\nKtóre wydarzenie mam usunąć? Podaj numer albo napisz „usuń oba/wszystkie”.", "event": {"operation": "delete", "search": criteria, "matches": events}}
            event = events[0]
            return {"status": "calendar_delete_confirmation", "message": f"Znalazłem „{event['title']}” o {event.get('start', '?')}. Czy chcesz je usunąć?", "event": {"operation": "delete", "search": criteria, "matches": [event]}}

        event_data = _merge_event(request.draft_event if state.get("operation", "create") == "create" else None, result.get("event"))
        if operation == "create":
            event_data = event_data or {"operation": "create"}
            event_data["operation"] = "create"
            missing = _missing_event(event_data)
            if not missing:
                return {"status": "ready_for_confirmation", "message": reply, "event": event_data}
            return {"status": "needs_input", "message": reply, "event": event_data}

        return {"status": status, "message": reply, "event": event_data}

    except CalendarAuthRequired as exc:
        return {"status": "calendar_auth_required", "message": "Google Calendar wymaga ponownej autoryzacji. Stan operacji został zachowany.", "error": str(exc), "event": request.draft_event}
    except (ValueError, json.JSONDecodeError) as exc:
        return {"status": "needs_input", "message": str(exc), "event": request.draft_event}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "event": request.draft_event}
