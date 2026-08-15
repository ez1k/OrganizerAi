import logging
import re
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter

from app.routes import chat
from app.schemas import ChatRequest
from app.services.metrics_service import save_chat_turn_metric

logger = logging.getLogger(__name__)
router = APIRouter()

CREATE_CANCEL_RE = re.compile(
    r"^\s*(?:anuluj(?:\s+to)?|nieważne|niewazne|odpuść|odpusc|zrezygnuj|nie\s+dodawaj)\s*[.!]?\s*$",
    re.I,
)
CREATE_DECLINE_RE = re.compile(
    r"^\s*(?:nie|nie\s+teraz|jeszcze\s+nie)\s*[.!]?\s*$",
    re.I,
)
CREATE_DAY_AT_RE = re.compile(
    r"\b(?:dzisiaj|dziś|jutro|pojutrze|poniedziałek|poniedzialek|wtorek|"
    r"środę|środa|srodę|srode|sroda|czwartek|piątek|piatek|sobotę|sobote|"
    r"sobota|niedzielę|niedziele|niedziela)\b"
    r"\s+na\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b",
    re.I,
)


def _is_create_cancel(message: str) -> bool:
    return bool(CREATE_CANCEL_RE.fullmatch(str(message or "")))


def _is_create_decline(message: str) -> bool:
    return bool(CREATE_DECLINE_RE.fullmatch(str(message or "")))


def _extract_create_time_override(message: str, state: dict) -> str | None:
    """Recognize colloquial CREATE phrases such as ``dziś na 16``.

    The core parser intentionally remains conservative. This wrapper only
    enriches the draft when the current context is CREATE or the message
    explicitly contains a CREATE intent.
    """
    text = str(message or "")
    is_create_context = state.get("operation") == "create" or bool(chat.CREATE_INTENT_RE.search(text))
    if not is_create_context:
        return None

    match = CREATE_DAY_AT_RE.search(text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    return f"{hour:02d}:{minute:02d}"


def _with_create_time_override(request: ChatRequest, state: dict) -> ChatRequest:
    time_hint = _extract_create_time_override(request.message, state)
    if not time_hint:
        return request

    enriched_draft = dict(request.draft_event or {})
    enriched_draft["operation"] = "create"
    enriched_draft["time_hint"] = time_hint

    if hasattr(request, "model_copy"):
        return request.model_copy(update={"draft_event": enriched_draft})
    return request.copy(update={"draft_event": enriched_draft})


def _session_id(request: ChatRequest) -> str:
    explicit = str(request.session_id or "").strip()
    if explicit:
        return explicit[:64]

    first_user_message = None
    for item in request.history:
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if role == "user" and content:
            first_user_message = str(content)
            break

    seed_message = first_user_message or request.message
    seed = f"OrganizerAI|{request.user_id}|{seed_message}"
    return str(uuid5(NAMESPACE_URL, seed))


def _infer_operation(request: ChatRequest, result: dict) -> str:
    event = result.get("event") if isinstance(result, dict) else None
    if isinstance(event, dict) and event.get("operation"):
        return str(event["operation"])

    draft = request.draft_event or {}
    if draft.get("operation"):
        return str(draft["operation"])

    status = str(result.get("status") or "") if isinstance(result, dict) else ""
    status_operations = {
        "confirmed": "create",
        "calendar_duplicate_confirmation": "create",
        "deleted": "delete",
        "calendar_delete_confirmation": "delete",
        "calendar_search": "search",
        "external_search": "external_search",
    }
    if status in status_operations:
        return status_operations[status]
    if chat.CREATE_INTENT_RE.search(request.message):
        return "create"
    return "chat"


def _finish(request: ChatRequest, result: dict, started_at: float) -> dict:
    latency_ms = max(0, round((perf_counter() - started_at) * 1000))
    status = str(result.get("status") or "unknown")

    try:
        save_chat_turn_metric(
            user_id=request.user_id,
            session_id=_session_id(request),
            operation=_infer_operation(request, result),
            status=status,
            latency_ms=latency_ms,
            clarification_required=status == "needs_input",
            had_draft=bool(request.draft_event),
            message_length=len(request.message),
        )
    except Exception:
        logger.exception("Failed to persist chat turn metric for user_id=%s", request.user_id)

    return result


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    started_at = perf_counter()
    state = request.draft_event or {}

    if state.get("operation") == "create":
        if _is_create_cancel(request.message):
            return _finish(
                request,
                {
                    "status": "cancelled",
                    "message": "Anulowano tworzenie wydarzenia. Nic nie zostało dodane do Google Calendar.",
                    "event": None,
                },
                started_at,
            )

        if _is_create_decline(request.message):
            if state.get("allow_duplicate"):
                return _finish(
                    request,
                    {
                        "status": "cancelled",
                        "message": "OK, nie dodaję kolejnego duplikatu do Google Calendar.",
                        "event": None,
                    },
                    started_at,
                )

            return _finish(
                request,
                {
                    "status": "ready_for_confirmation",
                    "message": (
                        "OK, jeszcze niczego nie dodaję. Napisz, co chcesz zmienić "
                        "— np. „jednak o 18”, „jutro o 19” albo „60 min”."
                    ),
                    "event": state,
                },
                started_at,
            )

    delegated_request = _with_create_time_override(request, state)
    result = chat.chat_endpoint(delegated_request)
    return _finish(request, result, started_at)
