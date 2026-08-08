import json
import re

from fastapi import APIRouter
from google.auth.exceptions import RefreshError

from app.schemas import ChatRequest
from app.services.date_parser import build_event_time
from app.services.google_calendar import create_event
from app.services.llm_service import ask_llm

router = APIRouter()

CONFIRMATION_RE = re.compile(
    r"^(?:tak|tak,|potwierdzam|potwierdź|dodaj|zapisz|zapisz to|jasne|zgadza się|zgadza sie|ok|okej|okay|yes)[.!\s]*$",
    re.IGNORECASE,
)


def _is_confirmation(message: str) -> bool:
    normalized = " ".join(message.strip().lower().split())
    if CONFIRMATION_RE.fullmatch(normalized):
        return True
    return normalized.startswith("tak") and bool(
        re.search(r"\bpotwierdz[a-ząćęłńóśźż]*\b", normalized)
    )


def _merge_event(draft: dict | None, candidate: dict | None) -> dict | None:
    """Merge only explicit values returned by the LLM into the conversation draft."""
    if not draft and not candidate:
        return None

    merged = dict(draft or {})
    for key in ("title", "date_hint", "duration_minutes", "description"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""):
            merged[key] = value
    return merged


def _missing_fields(event: dict | None) -> list[str]:
    if not event:
        return ["title", "date_hint"]

    missing = []
    if not str(event.get("title", "")).strip():
        missing.append("title")
    if not str(event.get("date_hint", "")).strip():
        missing.append("date_hint")
    return missing


def _build_event(data: dict) -> dict:
    title = str(data.get("title", "")).strip()
    date_hint = str(data.get("date_hint", "")).strip()
    description = str(data.get("description", "")).strip()
    duration = data.get("duration_minutes", 60)

    if not title or not date_hint:
        raise ValueError("Brakuje nazwy, dnia lub godziny wydarzenia.")

    try:
        duration = int(duration or 60)
    except (TypeError, ValueError):
        duration = 60

    if duration <= 0:
        duration = 60

    start, end = build_event_time(date_hint, duration)
    return {
        "title": title,
        "description": description,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _create_calendar_event(event: dict):
    try:
        return create_event(event)
    except (FileNotFoundError, RefreshError) as exc:
        # Calendar authentication is deliberately kept separate from the
        # conversation state. The frontend can ask the user to re-authenticate
        # without losing the already confirmed event draft.
        raise CalendarAuthRequired(str(exc)) from exc


class CalendarAuthRequired(Exception):
    pass


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    try:
        # Confirmation is an application state transition, not an LLM decision.
        if request.draft_event and _is_confirmation(request.message):
            missing = _missing_fields(request.draft_event)
            if missing:
                return {
                    "status": "needs_input",
                    "message": "Brakuje jeszcze danych wydarzenia. Uzupełnij je przed potwierdzeniem.",
                    "event": request.draft_event,
                }

            event = _build_event(request.draft_event)
            link = _create_calendar_event(event)
            return {
                "status": "confirmed",
                "message": f"Dodane: {event['title']}.",
                "event": event,
                "calendar_link": link,
            }

        history = []
        for item in request.history:
            if hasattr(item, "model_dump"):
                history.append(item.model_dump())
            else:
                history.append(item.dict())

        result = ask_llm(
            message=request.message,
            history=history,
            draft_event=request.draft_event,
        )

        status = result.get("status", "chat")
        reply = result.get("reply", "Nie udało mi się zrozumieć wiadomości.")
        event_data = _merge_event(request.draft_event, result.get("event"))

        if status == "cancelled":
            return {"status": "cancelled", "message": reply, "event": None}

        missing = _missing_fields(event_data)
        if not missing and status in {"ready_for_confirmation", "chat"}:
            return {
                "status": "ready_for_confirmation",
                "message": reply,
                "event": event_data,
            }

        return {
            "status": "needs_input" if missing else status,
            "message": reply,
            "event": event_data,
        }

    except CalendarAuthRequired as exc:
        return {
            "status": "calendar_auth_required",
            "message": "Google Calendar wymaga ponownej autoryzacji. Twoje wydarzenie nie zostało utracone.",
            "error": str(exc),
            "event": request.draft_event,
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "Model zwrócił niepoprawną odpowiedź JSON.",
            "event": request.draft_event,
        }
    except ValueError as exc:
        return {
            "status": "needs_input",
            "message": str(exc),
            "event": request.draft_event,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "event": request.draft_event,
        }
