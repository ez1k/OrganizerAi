"""Persistence helpers for dialog quality and performance evaluation metrics."""

from sqlalchemy import text

from app.services.database import get_engine, get_or_create_user_id

TIMING_VERSION = 1


def save_chat_turn_metric(
    user_id: str,
    session_id: str,
    operation: str,
    status: str,
    latency_ms: int,
    clarification_required: bool,
    had_draft: bool,
    message_length: int,
    llm_latency_ms: int = 0,
    calendar_latency_ms: int = 0,
    backend_latency_ms: int = 0,
    llm_calls: int = 0,
    calendar_calls: int = 0,
) -> None:
    """Persist one measured /chat turn without storing the raw user message."""
    database_user_id = get_or_create_user_id(user_id)

    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO dbo.chat_turn_metrics (
                    user_id,
                    session_id,
                    operation,
                    status,
                    latency_ms,
                    llm_latency_ms,
                    calendar_latency_ms,
                    backend_latency_ms,
                    llm_calls,
                    calendar_calls,
                    timing_version,
                    clarification_required,
                    had_draft,
                    message_length
                )
                VALUES (
                    :user_id,
                    :session_id,
                    :operation,
                    :status,
                    :latency_ms,
                    :llm_latency_ms,
                    :calendar_latency_ms,
                    :backend_latency_ms,
                    :llm_calls,
                    :calendar_calls,
                    :timing_version,
                    :clarification_required,
                    :had_draft,
                    :message_length
                )
                """
            ),
            {
                "user_id": database_user_id,
                "session_id": str(session_id),
                "operation": str(operation or "chat")[:32],
                "status": str(status or "unknown")[:64],
                "latency_ms": max(0, int(latency_ms)),
                "llm_latency_ms": max(0, int(llm_latency_ms)),
                "calendar_latency_ms": max(0, int(calendar_latency_ms)),
                "backend_latency_ms": max(0, int(backend_latency_ms)),
                "llm_calls": max(0, int(llm_calls)),
                "calendar_calls": max(0, int(calendar_calls)),
                "timing_version": TIMING_VERSION,
                "clarification_required": bool(clarification_required),
                "had_draft": bool(had_draft),
                "message_length": max(0, int(message_length)),
            },
        )
