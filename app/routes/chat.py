import json
import re

from fastapi import APIRouter

from app.schemas import ChatRequest
from app.services.date_parser import build_event_time
from app.services.google_calendar import create_event
from app.services.llm_service import ask_llm

router = APIRouter()


CONFIRMATION_RE = re.compile(
    r"^(tak|tak,|potwierdzam|potwierdź|dodaj|zapisz|zapisz to|jasne|zgadza się|zgadza sie|ok|okej|okay|yes)[.!\s]*$",
    re.IGNORECASE,
)


def _build_event(data: dict) -> dict:
    title = str(data.get("title", "")).strip()
    date_hint = str(data.get("date_hint", "")).strip()
    description = str(data.get("description", "")).strip()
    duration = data.get("duration_minutes", 60)

    if not title or not date_hint:
        raise ValueError("Event is missing title or date/time")

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


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    try:
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
        event_data = result.get("event")

        # The model is never allowed to create an event by itself.
        # Creation requires both a complete event and an explicit confirmation.
        if status == "confirmed":
            if not CONFIRMATION_RE.match(request.message.strip()):
                return {
                    "status": "ready_for_confirmation",
                    "message": "Czy na pewno mam dodać to wydarzenie?",
                    "event": request.draft_event,
                }

            event_data = event_data or request.draft_event
            if not event_data:
                return {
                    "status": "needs_input",
                    "message": "Brakuje danych wydarzenia. Jaki dzień i godzinę mam ustawić?",
                    "event": None,
                }

            event = _build_event(event_data)
            link = create_event(event)

            return {
                "status": "confirmed",
                "message": reply,
                "event": event,
                "calendar_link": link,
            }

        if status == "ready_for_confirmation":
            if not event_data:
                raise ValueError("LLM marked event as ready but returned no event")

            return {
                "status": "ready_for_confirmation",
                "message": reply,
                "event": event_data,
            }

        if status == "cancelled":
            return {
                "status": "cancelled",
                "message": reply,
                "event": None,
            }

        return {
            "status": status,
            "message": reply,
            "event": event_data,
        }

    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "Model zwrócił niepoprawną odpowiedź JSON.",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }
