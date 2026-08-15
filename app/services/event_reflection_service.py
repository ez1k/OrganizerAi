"""Persistence for post-event reflections and motivational reminders."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.services.database import get_engine, get_or_create_user_id

VALID_SENTIMENTS = {"positive", "neutral", "negative", "mixed"}
VALID_REMINDER_STATUSES = {"pending", "delivered", "completed", "dismissed"}


def _utc_naive(value: datetime) -> datetime:
    """Convert an API datetime to the UTC-naive representation stored in SQL Server."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _reflection_mapping(row) -> dict[str, Any]:
    item = dict(row)
    for key in ("event_start", "event_end", "created_at", "updated_at"):
        item[key] = _iso_utc(item.get(key))
    if item.get("rating") is not None:
        item["rating"] = int(item["rating"])
    if item.get("worth_repeating") is not None:
        item["worth_repeating"] = bool(item["worth_repeating"])
    item["id"] = int(item["id"])
    return item


def _reminder_mapping(row) -> dict[str, Any]:
    item = dict(row)
    for key in ("remind_at", "delivered_at", "completed_at", "created_at"):
        item[key] = _iso_utc(item.get(key))
    item["id"] = int(item["id"])
    item["reflection_id"] = int(item["reflection_id"])
    if item.get("rating") is not None:
        item["rating"] = int(item["rating"])
    if item.get("worth_repeating") is not None:
        item["worth_repeating"] = bool(item["worth_repeating"])
    return item


def save_event_reflection(
    *,
    user_id: str,
    calendar_event_id: str,
    event_title: str,
    event_start: datetime,
    event_end: datetime,
    rating: int | None = None,
    sentiment: str | None = None,
    feedback_text: str | None = None,
    worth_repeating: bool | None = None,
) -> dict[str, Any]:
    """Insert or update one user's reflection for a completed calendar event."""
    if rating is not None and not 1 <= int(rating) <= 5:
        raise ValueError("Ocena musi mieścić się w zakresie 1–5.")

    normalized_sentiment = str(sentiment or "").strip().lower() or None
    if normalized_sentiment is not None and normalized_sentiment not in VALID_SENTIMENTS:
        raise ValueError("Nieprawidłowy sentiment wydarzenia.")

    start_utc = _utc_naive(event_start)
    end_utc = _utc_naive(event_end)
    if end_utc < start_utc:
        raise ValueError("Koniec wydarzenia nie może być wcześniejszy niż początek.")

    database_user_id = get_or_create_user_id(user_id)
    params = {
        "user_id": database_user_id,
        "calendar_event_id": str(calendar_event_id).strip(),
        "event_title": str(event_title).strip(),
        "event_start": start_utc,
        "event_end": end_utc,
        "rating": rating,
        "sentiment": normalized_sentiment,
        "feedback_text": str(feedback_text).strip() if feedback_text else None,
        "worth_repeating": worth_repeating,
    }
    if not params["calendar_event_id"] or not params["event_title"]:
        raise ValueError("Wydarzenie musi mieć identyfikator i tytuł.")

    with get_engine().begin() as conn:
        reflection_id = conn.execute(
            text("""
                UPDATE dbo.event_reflections
                SET event_title = :event_title,
                    event_start = :event_start,
                    event_end = :event_end,
                    rating = :rating,
                    sentiment = :sentiment,
                    feedback_text = :feedback_text,
                    worth_repeating = :worth_repeating,
                    updated_at = SYSUTCDATETIME()
                OUTPUT INSERTED.id
                WHERE user_id = :user_id
                  AND calendar_event_id = :calendar_event_id
            """),
            params,
        ).scalar_one_or_none()

        if reflection_id is None:
            reflection_id = conn.execute(
                text("""
                    INSERT INTO dbo.event_reflections (
                        user_id,
                        calendar_event_id,
                        event_title,
                        event_start,
                        event_end,
                        rating,
                        sentiment,
                        feedback_text,
                        worth_repeating
                    )
                    OUTPUT INSERTED.id
                    VALUES (
                        :user_id,
                        :calendar_event_id,
                        :event_title,
                        :event_start,
                        :event_end,
                        :rating,
                        :sentiment,
                        :feedback_text,
                        :worth_repeating
                    )
                """),
                params,
            ).scalar_one()

        row = conn.execute(
            text("""
                SELECT id, calendar_event_id, event_title, event_start, event_end,
                       rating, sentiment, feedback_text, worth_repeating,
                       created_at, updated_at
                FROM dbo.event_reflections
                WHERE id = :id AND user_id = :user_id
            """),
            {"id": reflection_id, "user_id": database_user_id},
        ).mappings().one()

    return _reflection_mapping(row)


def list_event_reflections(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    database_user_id = get_or_create_user_id(user_id)
    safe_limit = max(1, min(int(limit), 100))
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT TOP {safe_limit}
                       id, calendar_event_id, event_title, event_start, event_end,
                       rating, sentiment, feedback_text, worth_repeating,
                       created_at, updated_at
                FROM dbo.event_reflections
                WHERE user_id = :user_id
                ORDER BY event_end DESC, id DESC
            """),
            {"user_id": database_user_id},
        ).mappings().all()
    return [_reflection_mapping(row) for row in rows]


def schedule_motivation_reminder(
    *,
    user_id: str,
    reflection_id: int,
    remind_at: datetime,
) -> dict[str, Any] | None:
    """Schedule a reminder only for a reflection owned by the requesting user."""
    database_user_id = get_or_create_user_id(user_id)
    remind_at_utc = _utc_naive(remind_at)

    with get_engine().begin() as conn:
        reflection_exists = conn.execute(
            text("""
                SELECT 1
                FROM dbo.event_reflections
                WHERE id = :reflection_id AND user_id = :user_id
            """),
            {"reflection_id": reflection_id, "user_id": database_user_id},
        ).scalar_one_or_none()
        if reflection_exists is None:
            return None

        reminder_id = conn.execute(
            text("""
                INSERT INTO dbo.motivation_reminders (
                    user_id, reflection_id, remind_at, status
                )
                OUTPUT INSERTED.id
                VALUES (:user_id, :reflection_id, :remind_at, N'pending')
            """),
            {
                "user_id": database_user_id,
                "reflection_id": reflection_id,
                "remind_at": remind_at_utc,
            },
        ).scalar_one()

        row = _load_reminder(conn, database_user_id, int(reminder_id))

    return _reminder_mapping(row) if row is not None else None


def _load_reminder(conn, database_user_id: str, reminder_id: int):
    return conn.execute(
        text("""
            SELECT r.id, r.reflection_id, r.remind_at, r.status,
                   r.delivered_at, r.completed_at, r.created_at,
                   e.calendar_event_id, e.event_title, e.event_start, e.event_end,
                   e.rating, e.sentiment, e.feedback_text, e.worth_repeating
            FROM dbo.motivation_reminders r
            JOIN dbo.event_reflections e ON e.id = r.reflection_id
            WHERE r.id = :reminder_id
              AND r.user_id = :user_id
              AND e.user_id = :user_id
        """),
        {"reminder_id": reminder_id, "user_id": database_user_id},
    ).mappings().one_or_none()


def list_due_motivation_reminders(
    user_id: str,
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return reminders that are due but have not yet been delivered."""
    database_user_id = get_or_create_user_id(user_id)
    now_utc = _utc_naive(now or datetime.now(timezone.utc))
    safe_limit = max(1, min(int(limit), 100))

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT TOP {safe_limit}
                       r.id, r.reflection_id, r.remind_at, r.status,
                       r.delivered_at, r.completed_at, r.created_at,
                       e.calendar_event_id, e.event_title, e.event_start, e.event_end,
                       e.rating, e.sentiment, e.feedback_text, e.worth_repeating
                FROM dbo.motivation_reminders r
                JOIN dbo.event_reflections e ON e.id = r.reflection_id
                WHERE r.user_id = :user_id
                  AND e.user_id = :user_id
                  AND r.status = N'pending'
                  AND r.remind_at <= :now
                ORDER BY r.remind_at ASC, r.id ASC
            """),
            {"user_id": database_user_id, "now": now_utc},
        ).mappings().all()

    return [_reminder_mapping(row) for row in rows]


def update_motivation_reminder_status(
    *,
    user_id: str,
    reminder_id: int,
    status: str,
) -> dict[str, Any] | None:
    """Advance a reminder without ever creating a Calendar event automatically."""
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"delivered", "completed", "dismissed"}:
        raise ValueError("Nieprawidłowy status przypomnienia.")

    database_user_id = get_or_create_user_id(user_id)
    with get_engine().begin() as conn:
        updated_id = conn.execute(
            text("""
                UPDATE dbo.motivation_reminders
                SET status = :status,
                    delivered_at = CASE
                        WHEN :status = N'delivered' AND delivered_at IS NULL THEN SYSUTCDATETIME()
                        WHEN :status IN (N'completed', N'dismissed') AND delivered_at IS NULL THEN SYSUTCDATETIME()
                        ELSE delivered_at
                    END,
                    completed_at = CASE
                        WHEN :status IN (N'completed', N'dismissed') THEN SYSUTCDATETIME()
                        ELSE completed_at
                    END
                OUTPUT INSERTED.id
                WHERE id = :reminder_id
                  AND user_id = :user_id
            """),
            {
                "status": normalized_status,
                "reminder_id": reminder_id,
                "user_id": database_user_id,
            },
        ).scalar_one_or_none()
        if updated_id is None:
            return None
        row = _load_reminder(conn, database_user_id, int(updated_id))

    return _reminder_mapping(row) if row is not None else None
