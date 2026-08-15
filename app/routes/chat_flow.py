import logging
import re
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter

from app.routes import chat
from app.schemas import ChatRequest
from app.services.metrics_service import save_chat_turn_metric
from app.services.turn_timing import (
    reset_turn_timing,
    snapshot_turn_timing,
    start_turn_timing,
)

logger = logging.getLogger(__name__)
router = APIRouter()

CREATE_CANCEL_RE = re.compile(
    r"^\s*(?:(?:a|albo|dobra|no|to|w\s+sumie|jednak)\s*[,\-]?\s+)*"
    r"(?:anuluj(?:\s+to)?|nieważne|niewazne|odpuść|odpusc|zrezygnuj|nie\s+dodawaj)"
    r"(?:\s*[,\-]?\s+(?:jednak|w\s+sumie|dobra|proszę|prosze))?\s*[.!]?\s*$",
    re.I,
)
CREATE_DECLINE_RE = re.compile(
    r"^\s*(?:nie|nie\s+teraz|jeszcze\s+nie)\s*[.!]?\s*$",
    re.I,
)
CREATE_CONFIRM_RE = re.compile(
    r"^\s*(?:tak\s*,?\s*(?:dodaj|zapisz)(?:\s+to)?|tak|ok\s+dodaj|okej\s+dodaj|"
    r"no\s+dodaj|dawaj|dodawaj|dodaj(?:\s+to)?|zapisz(?:\s+to)?)\s*[.!]?\s*$",
    re.I,
)
DELETE_CONFIRM_RE = re.compile(
    r"^\s*(?:tak(?:\s*,?\s*(?:usuń|usun|skasuj|wywal)(?:\s+to)?)?|"
    r"potwierdzam|potwierdź|potwierdz|zgadza\s+się|zgadza\s+sie)\s*[.!]?\s*$",
    re.I,
)
DELETE_CANCEL_RE = re.compile(
    r"^\s*(?:(?:a|albo|dobra|no|to|w\s+sumie)\s*[,\-]?\s+)*"
    r"(?:nie(?:\s+teraz)?|jednak\s+nie|nie\s+usuwaj|anuluj(?:\s+to)?|"
    r"nieważne|niewazne|odpuść|odpusc|zrezygnuj)"
    r"(?:\s*[,\-]?\s+(?:jednak|w\s+sumie|dobra))?\s*[.!]?\s*$",
    re.I,
)
DUPLICATE_DECLINE_RE = re.compile(
    r"^\s*(?:a\s+)?(?:to\s+)?(?:w\s+takim\s+razie\s+)?(?:jednak\s+)?nie\s*[.!]?\s*$",
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


def _is_create_confirmation(message: str) -> bool:
    return bool(CREATE_CONFIRM_RE.fullmatch(str(message or "")))


def _is_delete_confirmation(message: str) -> bool:
    return bool(DELETE_CONFIRM_RE.fullmatch(str(message or "")))


def _is_delete_cancel(message: str) -> bool:
    return bool(DELETE_CANCEL_RE.fullmatch(str(message or "")))


def _is_duplicate_decline(message: str) -> bool:
    return bool(DUPLICATE_DECLINE_RE.fullmatch(str(message or "")))


def _copy_request(request: ChatRequest, **updates) -> ChatRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(update=updates)
    return request.copy(update=updates)


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
    return _copy_request(request, draft_event=enriched_draft)


def _with_normalized_create_confirmation(request: ChatRequest, state: dict) -> ChatRequest:
    """Map natural confirmation variants to the core backend's canonical ``tak``.

    The original request is still used for metrics; only the delegated request
    is normalized so phrases such as ``tak dodaj`` do not fall through to the LLM.
    """
    if state.get("operation") != "create" or not _is_create_confirmation(request.message):
        return request
    return _copy_request(request, message="tak")


def _with_normalized_delete_confirmation(request: ChatRequest, state: dict) -> ChatRequest:
    """Normalize only explicit DELETE confirmations to the core canonical ``tak``."""
    if state.get("operation") != "delete" or not _is_delete_confirmation(request.message):
        return request
    return _copy_request(request, message="tak")


def _deterministic_create_fast_path(request: ChatRequest, state: dict) -> dict | None:
    """Handle safe CREATE parsing without LLM when intent and slots are explicit.

    Complete drafts go straight to the confirmation summary. If exactly one
    required slot is missing, the backend asks for that slot deterministically.
    More ambiguous cases still fall back to the core router/LLM.
    """
    is_create_context = state.get("operation") == "create" or bool(
        chat.CREATE_INTENT_RE.search(request.message)
    )
    if not is_create_context:
        return None

    if state.get("operation") == "create" and (
        _is_create_confirmation(request.message)
        or chat._asks_if_create_was_committed(request.message)
        or chat._asks_for_missing_create_data(request.message)
    ):
        return None

    fields = chat._extract_create_fields(
        request.message,
        continuation=state.get("operation") == "create",
    )
    time_override = _extract_create_time_override(request.message, state)
    if time_override:
        fields["time_hint"] = time_override

    if not fields:
        return None

    event = {
        key: value
        for key, value in state.items()
        if key in {"title", "date_hint", "time_hint", "duration_minutes", "description"}
    }
    event.update(fields)
    event["operation"] = "create"

    missing = chat._missing_event(event)
    if not missing:
        return {
            "status": "ready_for_confirmation",
            "message": chat._create_confirmation_message(event),
            "event": event,
        }

    if len(missing) == 1:
        return {
            "status": "needs_input",
            "message": chat._create_missing_message(event, missing),
            "event": event,
        }

    return None


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
    components = snapshot_turn_timing()
    llm_latency_ms = components["llm_latency_ms"]
    calendar_latency_ms = components["calendar_latency_ms"]
    backend_latency_ms = max(0, latency_ms - llm_latency_ms - calendar_latency_ms)

    try:
        save_chat_turn_metric(
            user_id=request.user_id,
            session_id=_session_id(request),
            operation=_infer_operation(request, result),
            status=status,
            latency_ms=latency_ms,
            llm_latency_ms=llm_latency_ms,
            calendar_latency_ms=calendar_latency_ms,
            backend_latency_ms=backend_latency_ms,
            llm_calls=components["llm_calls"],
            calendar_calls=components["calendar_calls"],
            clarification_required=status == "needs_input",
            had_draft=bool(request.draft_event),
            message_length=len(request.message),
        )
    except Exception:
        logger.exception("Failed to persist chat turn metric for user_id=%s", request.user_id)

    return result


def _chat_endpoint_inner(request: ChatRequest, started_at: float):
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

        if state.get("allow_duplicate") and _is_duplicate_decline(request.message):
            return _finish(
                request,
                {
                    "status": "cancelled",
                    "message": "OK, nie dodaję kolejnego duplikatu do Google Calendar.",
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

    if state.get("operation") == "delete":
        if _is_delete_cancel(request.message):
            return _finish(
                request,
                {
                    "status": "cancelled",
                    "message": "OK, anulowano usuwanie. Żadne wydarzenie nie zostało usunięte.",
                    "event": None,
                },
                started_at,
            )

        if chat._is_confirmation(request.message) and not _is_delete_confirmation(request.message):
            return _finish(
                request,
                {
                    "status": "calendar_delete_confirmation",
                    "message": (
                        "Dla bezpieczeństwa potwierdź usunięcie jednoznacznie — "
                        "napisz „tak”, „tak usuń” albo „potwierdzam”."
                    ),
                    "event": state,
                },
                started_at,
            )

    fast_path_result = _deterministic_create_fast_path(request, state)
    if fast_path_result is not None:
        return _finish(request, fast_path_result, started_at)

    delegated_request = _with_create_time_override(request, state)
    delegated_state = delegated_request.draft_event or state
    delegated_request = _with_normalized_create_confirmation(delegated_request, delegated_state)
    delegated_request = _with_normalized_delete_confirmation(delegated_request, delegated_state)
    result = chat.chat_endpoint(delegated_request)
    return _finish(request, result, started_at)


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    started_at = perf_counter()
    timing_token = start_turn_timing()
    try:
        return _chat_endpoint_inner(request, started_at)
    finally:
        reset_turn_timing(timing_token)
