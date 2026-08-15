"""API for post-event reflections and motivational reminders."""

import logging

import requests
from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    EventReflectionRequest,
    MotivationReminderRequest,
    MotivationReminderStatusRequest,
    ReflectionAnalysisRequest,
)
from app.services.event_reflection_service import (
    list_due_motivation_reminders,
    list_event_reflections,
    save_event_reflection,
    schedule_motivation_reminder,
    update_motivation_reminder_status,
)
from app.services.reflection_nlp_service import analyze_event_reflection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reflections"])


@router.post("/reflections")
def create_or_update_reflection(request: EventReflectionRequest):
    try:
        reflection = save_event_reflection(
            user_id=request.user_id,
            calendar_event_id=request.calendar_event_id,
            event_title=request.event_title,
            event_start=request.event_start,
            event_end=request.event_end,
            rating=request.rating,
            sentiment=request.sentiment,
            feedback_text=request.feedback_text,
            worth_repeating=request.worth_repeating,
        )
        return {"status": "saved", "reflection": reflection}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save event reflection for user_id=%s", request.user_id)
        raise HTTPException(status_code=500, detail="Nie udało się zapisać oceny wydarzenia.") from exc


@router.get("/reflections")
def get_reflections(
    user_id: str = "local-user",
    limit: int = Query(default=50, ge=1, le=100),
):
    try:
        return {"reflections": list_event_reflections(user_id, limit=limit)}
    except Exception as exc:
        logger.exception("Failed to list event reflections for user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Nie udało się pobrać ocen wydarzeń.") from exc


@router.post("/reflections/analyze")
def analyze_reflection(request: ReflectionAnalysisRequest):
    """Analyze natural-language event feedback without persisting or scheduling anything."""
    try:
        analysis = analyze_event_reflection(request.feedback_text)
        return {"status": "analyzed", "analysis": analysis}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("Failed to reach local reflection NLP model")
        raise HTTPException(
            status_code=503,
            detail="Nie udało się połączyć z lokalnym modelem analizującym ocenę wydarzenia.",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to analyze event reflection")
        raise HTTPException(status_code=500, detail="Nie udało się przeanalizować oceny wydarzenia.") from exc


@router.post("/reflections/{reflection_id}/reminders")
def create_motivation_reminder(reflection_id: int, request: MotivationReminderRequest):
    try:
        reminder = schedule_motivation_reminder(
            user_id=request.user_id,
            reflection_id=reflection_id,
            remind_at=request.remind_at,
        )
        if reminder is None:
            raise HTTPException(status_code=404, detail="Nie znaleziono oceny wydarzenia dla tego użytkownika.")
        return {"status": "scheduled", "reminder": reminder}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to schedule reminder for reflection_id=%s", reflection_id)
        raise HTTPException(status_code=500, detail="Nie udało się zapisać przypomnienia.") from exc


@router.get("/motivation-reminders/due")
def get_due_motivation_reminders(
    user_id: str = "local-user",
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        return {"reminders": list_due_motivation_reminders(user_id, limit=limit)}
    except Exception as exc:
        logger.exception("Failed to load due motivation reminders for user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Nie udało się pobrać przypomnień.") from exc


@router.post("/motivation-reminders/{reminder_id}/status")
def set_motivation_reminder_status(
    reminder_id: int,
    request: MotivationReminderStatusRequest,
):
    try:
        reminder = update_motivation_reminder_status(
            user_id=request.user_id,
            reminder_id=reminder_id,
            status=request.status,
        )
        if reminder is None:
            raise HTTPException(status_code=404, detail="Nie znaleziono przypomnienia dla tego użytkownika.")
        return {"status": reminder["status"], "reminder": reminder}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update motivation reminder id=%s", reminder_id)
        raise HTTPException(status_code=500, detail="Nie udało się zaktualizować przypomnienia.") from exc
