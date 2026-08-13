import re

from fastapi import APIRouter

from app.routes import chat
from app.schemas import ChatRequest

router = APIRouter()

CREATE_CANCEL_RE = re.compile(
    r"^\s*(?:anuluj(?:\s+to)?|nieważne|niewazne|odpuść|odpusc|zrezygnuj|nie\s+dodawaj)\s*[.!]?\s*$",
    re.I,
)
CREATE_DECLINE_RE = re.compile(
    r"^\s*(?:nie|nie\s+teraz|jeszcze\s+nie)\s*[.!]?\s*$",
    re.I,
)


def _is_create_cancel(message: str) -> bool:
    return bool(CREATE_CANCEL_RE.fullmatch(str(message or "")))


def _is_create_decline(message: str) -> bool:
    return bool(CREATE_DECLINE_RE.fullmatch(str(message or "")))


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    state = request.draft_event or {}

    if state.get("operation") == "create":
        if _is_create_cancel(request.message):
            return {
                "status": "cancelled",
                "message": "Anulowano tworzenie wydarzenia. Nic nie zostało dodane do Google Calendar.",
                "event": None,
            }

        if _is_create_decline(request.message):
            if state.get("allow_duplicate"):
                return {
                    "status": "cancelled",
                    "message": "OK, nie dodaję kolejnego duplikatu do Google Calendar.",
                    "event": None,
                }

            return {
                "status": "ready_for_confirmation",
                "message": (
                    "OK, jeszcze niczego nie dodaję. Napisz, co chcesz zmienić "
                    "— np. „jednak o 18”, „jutro o 19” albo „60 min”."
                ),
                "event": state,
            }

    return chat.chat_endpoint(request)
