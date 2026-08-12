"""Feedback endpoints used to build verified few-shot learning examples."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas import FeedbackCorrectionRequest, FeedbackRequest
from app.services.database import (
    save_conversation_feedback,
    verify_conversation_feedback,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feedback", tags=["feedback"])

_EVENT_FIELDS = ("title", "date_hint", "time_hint", "duration_minutes", "description")
_SEARCH_FIELDS = ("title", "date_hint", "time_hint", "range_type", "range_days")


def _clean_mapping(source: dict[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any]:
    source = source or {}
    return {key: source.get(key) for key in fields if source.get(key) not in (None, "")}


def normalize_learning_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    """Strip runtime-only state such as Calendar matches and event IDs."""
    if not isinstance(raw_result, dict):
        raise ValueError("Feedback result must be an object.")

    operation = str(raw_result.get("operation") or "").strip().lower()
    if operation == "create":
        event_source = raw_result.get("event") if isinstance(raw_result.get("event"), dict) else raw_result
        event = _clean_mapping(event_source, _EVENT_FIELDS)
        if not event:
            raise ValueError("Create feedback does not contain event fields.")
        return {"operation": "create", "event": event}

    if operation in {"search", "delete"}:
        search = _clean_mapping(
            raw_result.get("search") if isinstance(raw_result.get("search"), dict) else {},
            _SEARCH_FIELDS,
        )
        return {"operation": operation, "search": search}

    raise ValueError("Only create/search/delete interpretations can be used for learning.")


@router.post("")
def submit_feedback(request: FeedbackRequest):
    """Store positive or negative feedback for one backend interpretation."""
    try:
        normalized = normalize_learning_result(request.result)
        feedback_id = save_conversation_feedback(
            request.user_id,
            request.message,
            normalized,
        )

        if request.accepted:
            verified = verify_conversation_feedback(
                request.user_id,
                feedback_id,
                normalized,
            )
            if not verified:
                raise RuntimeError("Could not verify newly created feedback row.")
            return {
                "status": "verified",
                "feedback_id": feedback_id,
                "message": "Interpretacja została zapisana jako zweryfikowany przykład.",
            }

        return {
            "status": "needs_correction",
            "feedback_id": feedback_id,
            "message": "Interpretacja została oznaczona jako błędna. Następna poprawna interpretacja może ją skorygować.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save conversation feedback for user_id=%s", request.user_id)
        raise HTTPException(status_code=500, detail="Nie udało się zapisać feedbacku.") from exc


@router.post("/{feedback_id}/correction")
def submit_feedback_correction(feedback_id: int, request: FeedbackCorrectionRequest):
    """Attach a corrected interpretation and promote it to trusted learning data."""
    try:
        normalized = normalize_learning_result(request.corrected_result)
        verified = verify_conversation_feedback(
            request.user_id,
            feedback_id,
            normalized,
        )
        if not verified:
            raise HTTPException(status_code=404, detail="Nie znaleziono feedbacku dla tego użytkownika.")
        return {
            "status": "corrected",
            "feedback_id": feedback_id,
            "message": "Poprawiona interpretacja została zapisana jako zweryfikowany przykład.",
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to correct feedback id=%s", feedback_id)
        raise HTTPException(status_code=500, detail="Nie udało się zapisać poprawki.") from exc
