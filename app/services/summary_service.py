"""User-facing summary statistics for the OrganizerAI dashboard."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.services.database import get_engine, get_or_create_user_id
from app.services.google_calendar import list_recent_completed_events

WARSAW = ZoneInfo("Europe/Warsaw")
SENTIMENT_KEYS = ("positive", "neutral", "mixed", "negative")


def _as_int(value: Any) -> int:
    return int(value or 0)


def _as_float(value: Any) -> float:
    return float(value or 0.0)


def _parse_calendar_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return datetime.fromisoformat(raw).replace(tzinfo=WARSAW)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=WARSAW)
        return parsed.astimezone(WARSAW)
    except ValueError:
        return None


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _weekly_activity(events: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """Build continuous Monday-based buckets for completed Calendar events."""
    today = datetime.now(WARSAW).date()
    first_day = today - timedelta(days=max(1, days) - 1)
    first_week = _week_start(first_day)
    last_week = _week_start(today)

    counts: Counter[date] = Counter()
    for event in events:
        parsed = _parse_calendar_datetime(event.get("start"))
        if parsed is None:
            continue
        counts[_week_start(parsed.date())] += 1

    rows = []
    cursor = first_week
    while cursor <= last_week:
        week_end = cursor + timedelta(days=6)
        rows.append(
            {
                "week_start": cursor.isoformat(),
                "label": f"{cursor.strftime('%d.%m')}–{week_end.strftime('%d.%m')}",
                "count": int(counts.get(cursor, 0)),
            }
        )
        cursor += timedelta(days=7)
    return rows


def _top_activities(reflections: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Aggregate reflection history by title without inventing a productivity score."""
    grouped: dict[str, dict[str, Any]] = {}
    for reflection in reflections:
        title = str(reflection.get("event_title") or "").strip()
        if not title:
            continue

        key = title.casefold()
        item = grouped.setdefault(
            key,
            {
                "title": title,
                "ratings": [],
                "reflection_count": 0,
                "worth_repeating_count": 0,
                "last_event_end": reflection.get("event_end"),
            },
        )
        item["reflection_count"] += 1
        if reflection.get("rating") is not None:
            item["ratings"].append(int(reflection["rating"]))
        if reflection.get("worth_repeating") is True:
            item["worth_repeating_count"] += 1

        if str(reflection.get("event_end") or "") > str(item.get("last_event_end") or ""):
            item["last_event_end"] = reflection.get("event_end")
            item["title"] = title

    result = []
    for item in grouped.values():
        ratings = item.pop("ratings")
        average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
        result.append({**item, "average_rating": average_rating})

    result.sort(
        key=lambda item: (
            item["average_rating"] if item["average_rating"] is not None else -1,
            item["worth_repeating_count"],
            item["reflection_count"],
            str(item.get("last_event_end") or ""),
        ),
        reverse=True,
    )
    return result[: max(1, int(limit))]


def build_user_summary(user_id: str, *, days: int = 30) -> dict[str, Any]:
    """Combine Calendar activity with reflection, reminder, and chat metrics."""
    safe_days = max(7, min(int(days), 90))
    database_user_id = get_or_create_user_id(user_id)
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = (now_utc - timedelta(days=safe_days)).replace(tzinfo=None)

    with get_engine().connect() as conn:
        reflection_rows = conn.execute(
            text(
                """
                SELECT id, event_title, event_start, event_end, rating,
                       sentiment, worth_repeating, created_at
                FROM dbo.event_reflections
                WHERE user_id = :user_id
                  AND event_end >= :cutoff
                ORDER BY event_end DESC, id DESC
                """
            ),
            {"user_id": database_user_id, "cutoff": cutoff_utc},
        ).mappings().all()

        reminder_rows = conn.execute(
            text(
                """
                SELECT status, COUNT(*) AS total
                FROM dbo.motivation_reminders
                WHERE user_id = :user_id
                  AND created_at >= :cutoff
                GROUP BY status
                """
            ),
            {"user_id": database_user_id, "cutoff": cutoff_utc},
        ).mappings().all()

        active_reminders = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dbo.motivation_reminders
                WHERE user_id = :user_id
                  AND status = N'pending'
                """
            ),
            {"user_id": database_user_id},
        ).scalar_one()

        metric_row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS turns,
                    COUNT(DISTINCT session_id) AS sessions,
                    COALESCE(SUM(llm_calls), 0) AS llm_calls,
                    COALESCE(SUM(calendar_calls), 0) AS calendar_calls,
                    COALESCE(SUM(CASE WHEN llm_calls = 0 THEN 1 ELSE 0 END), 0) AS no_llm_turns,
                    COALESCE(SUM(CASE WHEN clarification_required = 1 THEN 1 ELSE 0 END), 0) AS clarification_turns,
                    COALESCE(AVG(CAST(latency_ms AS FLOAT)), 0) AS avg_latency_ms,
                    COALESCE(AVG(CAST(llm_latency_ms AS FLOAT)), 0) AS avg_llm_latency_ms,
                    COALESCE(AVG(CAST(calendar_latency_ms AS FLOAT)), 0) AS avg_calendar_latency_ms
                FROM dbo.chat_turn_metrics
                WHERE user_id = :user_id
                  AND created_at >= :cutoff
                """
            ),
            {"user_id": database_user_id, "cutoff": cutoff_utc},
        ).mappings().one()

        operation_rows = conn.execute(
            text(
                """
                SELECT operation, COUNT(*) AS total
                FROM dbo.chat_turn_metrics
                WHERE user_id = :user_id
                  AND created_at >= :cutoff
                GROUP BY operation
                ORDER BY total DESC, operation ASC
                """
            ),
            {"user_id": database_user_id, "cutoff": cutoff_utc},
        ).mappings().all()

    reflections = [dict(row) for row in reflection_rows]
    ratings = [
        int(item["rating"])
        for item in reflections
        if item.get("rating") is not None
    ]
    sentiment_counts = Counter(
        str(item.get("sentiment") or "").lower()
        for item in reflections
        if item.get("sentiment")
    )
    worth_repeating = {
        "yes": sum(item.get("worth_repeating") is True for item in reflections),
        "no": sum(item.get("worth_repeating") is False for item in reflections),
        "unknown": sum(item.get("worth_repeating") is None for item in reflections),
    }

    reminder_counts = {str(row["status"]): int(row["total"]) for row in reminder_rows}
    for status in ("pending", "delivered", "completed", "dismissed"):
        reminder_counts.setdefault(status, 0)

    calendar_available = True
    calendar_error = None
    try:
        completed_events = list_recent_completed_events(
            days=safe_days,
            max_results=100,
        )
    except Exception as exc:
        completed_events = []
        calendar_available = False
        calendar_error = str(exc)

    return {
        "period_days": safe_days,
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "calendar_available": calendar_available,
        "calendar_error": calendar_error,
        "overview": {
            "completed_events": len(completed_events),
            "reflections": len(reflections),
            "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "worth_repeating": worth_repeating["yes"],
            "active_reminders": _as_int(active_reminders),
        },
        "weekly_activity": _weekly_activity(completed_events, safe_days),
        "sentiments": {
            key: int(sentiment_counts.get(key, 0))
            for key in SENTIMENT_KEYS
        },
        "worth_repeating": worth_repeating,
        "top_activities": _top_activities(reflections),
        "reminders": reminder_counts,
        "assistant_usage": {
            "turns": _as_int(metric_row.get("turns")),
            "sessions": _as_int(metric_row.get("sessions")),
            "llm_calls": _as_int(metric_row.get("llm_calls")),
            "calendar_calls": _as_int(metric_row.get("calendar_calls")),
            "no_llm_turns": _as_int(metric_row.get("no_llm_turns")),
            "clarification_turns": _as_int(metric_row.get("clarification_turns")),
            "avg_latency_ms": round(_as_float(metric_row.get("avg_latency_ms")), 1),
            "avg_llm_latency_ms": round(_as_float(metric_row.get("avg_llm_latency_ms")), 1),
            "avg_calendar_latency_ms": round(_as_float(metric_row.get("avg_calendar_latency_ms")), 1),
            "operations": [
                {
                    "operation": str(row.get("operation") or "chat"),
                    "count": int(row.get("total") or 0),
                }
                for row in operation_rows
            ],
        },
    }
