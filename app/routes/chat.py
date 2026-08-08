import json
import re
from datetime import datetime, timedelta

from fastapi import APIRouter
from google.auth.exceptions import RefreshError

from app.services.date_parser import build_event_time
from app.services.google_calendar import create_event, delete_event, search_events
from app.services.llm_service import ask_llm
from app.schemas import ChatRequest

router = APIRouter()

CONFIRMATION_RE = re.compile(
    r"^(?:tak|tak,|potwierdzam|potwierdź|dodaj|zapisz|jasne|zgadza się|zgadza sie|ok|okej|okay|yes)[.!\s]*$",
    re.IGNORECASE,
)


def _is_confirmation(message: str) -> bool:
    normalized = " ".join(message.strip().lower().split())
    if CONFIRMATION_RE.fullmatch(normalized):
        return True
    return normalized.startswith("tak") and "potwierdz" in normalized


def _is_number_selection(message: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*[.]?\s*", message)
    return int(match.group(1)) if match else None


def _merge_event(draft, candidate):
    if not draft and not candidate:
        return None
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint", "duration_minutes", "description"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged


def _merge_search(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged


def _missing_event(event):
    if not event:
        return ["title", "date_hint", "time_hint"]
    return [
        key
        for key in ("title", "date_hint", "time_hint")
        if not str(event.get(key, "")).strip()
    ]


def _build_event(data):
    title = str(data.get("title", "")).strip()
    date_hint = str(data.get("date_hint", "")).strip()
    time_hint = str(data.get("time_hint", "")).strip()
    duration = int(data.get("duration_minutes") or 60)
    if not title or not date_hint or not time_hint:
        raise ValueError("Brakuje nazwy, dnia lub godziny wydarzenia.")
    start, end = build_event_time(f"{date_hint} o {time_hint}", duration)
    return {
        "title": title,
        "description": str(data.get("description", "")).strip(),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _day_range(date_hint: str):
    start, _ = build_event_time(f"{date_hint} o 00:00", 1)
    end = start + timedelta(days=1)
    return start, end


def _search_calendar(criteria):
    title = str(criteria.get("title", "")).strip() or None
    date_hint = str(criteria.get("date_hint", "")).strip()
    time_hint = str(criteria.get("time_hint", "")).strip()

    if date_hint:
        day_start, day_end = _day_range(date_hint)
        if time_hint:
            target, _ = build_event_time(f"{date_hint} o {time_hint}", 1)
            day_start = target - timedelta(minutes=1)
            day_end = target + timedelta(minutes=1)
        return search_events(
            query=title,
            time_min=day_start,
            time_max=day_end,
            max_results=20,
        )

    return search_events(query=title, max_results=20)


def _format_events(events):
    if not events:
        return "Nie znalazłem żadnych wydarzeń."
    lines = []
    for index, event in enumerate(events, 1):
        lines.append(
            f"{index}. {event['title']} — {event.get('start', '?')} – {event.get('end', '?')}"
        )
    return "Znalazłem:\n" + "\n".join(lines)


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

        # A numeric answer selects an item from the previous calendar search.
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

        # Confirm a pending DELETE without asking the LLM again.
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

        # Confirm a pending CREATE deterministically.
        if state.get("operation") == "create" and _is_confirmation(request.message):
            missing = _missing_event(state)
            if missing:
                return {
                    "status": "needs_input",
                    "message": "Brakuje jeszcze danych wydarzenia.",
                    "event": state,
                }
            event = _build_event(state)
            link = _calendar_call(create_event, event)
            return {
                "status": "confirmed",
                "message": f"Dodane: {event['title']}.",
                "event": event,
                "calendar_link": link,
            }

        history = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in request.history
        ]
        result = ask_llm(
            message=request.message,
            history=history,
            draft_event=request.draft_event,
        )
        operation = result.get("operation", "chat")
        status = result.get("status", "chat")
        reply = result.get("reply", "")

        # External questions are intentionally not sent to the calendar. The
        # current app has no external web-search provider, so never fabricate
        # an answer such as a movie time.
        if operation == "external_search":
            return {
                "status": "external_search",
                "message": "To pytanie dotyczy informacji spoza kalendarza. Nie mam jeszcze podłączonego wyszukiwania internetowego, więc nie będę zgadywać odpowiedzi.",
                "event": None,
            }

        if operation == "search":
            criteria = _merge_search(
                state.get("search") if state.get("operation") == "search" else None,
                result.get("search"),
            )
            events = _calendar_call(_search_calendar, criteria)
            return {
                "status": "calendar_search",
                "message": _format_events(events),
                "event": {
                    "operation": "search",
                    "search": criteria,
                    "matches": events,
                },
            }

        if operation == "delete":
            # Pronouns such as "ten drugi", "poprzedni" and "go" should use
            # the previous search result instead of creating a new event.
            previous_matches = _last_matches(state)
            criteria = _merge_search(
                state.get("search") if state.get("operation") in {"search", "delete"} else None,
                result.get("search"),
            )
            if previous_matches and not any(criteria.values()):
                events = previous_matches
            else:
                events = _calendar_call(_search_calendar, criteria)

            if not events:
                return {
                    "status": "chat",
                    "message": "Nie znalazłem pasującego wydarzenia do usunięcia.",
                    "event": None,
                }
            if len(events) > 1:
                return {
                    "status": "calendar_delete_confirmation",
                    "message": _format_events(events) + "\nKtóre wydarzenie mam usunąć? Podaj numer.",
                    "event": {
                        "operation": "delete",
                        "search": criteria,
                        "matches": events,
                    },
                }
            event = events[0]
            return {
                "status": "calendar_delete_confirmation",
                "message": f"Znalazłem „{event['title']}” o {event.get('start', '?')}. Czy chcesz je usunąć?",
                "event": {
                    "operation": "delete",
                    "search": criteria,
                    "matches": [event],
                },
            }

        event_data = _merge_event(
            request.draft_event if state.get("operation", "create") == "create" else None,
            result.get("event"),
        )
        if operation == "create":
            event_data = event_data or {"operation": "create"}
            event_data["operation"] = "create"
            missing = _missing_event(event_data)
            if not missing:
                return {
                    "status": "ready_for_confirmation",
                    "message": reply,
                    "event": event_data,
                }
            return {"status": "needs_input", "message": reply, "event": event_data}

        return {"status": status, "message": reply, "event": event_data}

    except CalendarAuthRequired as exc:
        return {
            "status": "calendar_auth_required",
            "message": "Google Calendar wymaga ponownej autoryzacji. Stan operacji został zachowany.",
            "error": str(exc),
            "event": request.draft_event,
        }
    except (ValueError, json.JSONDecodeError) as exc:
        return {"status": "needs_input", "message": str(exc), "event": request.draft_event}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "event": request.draft_event}
