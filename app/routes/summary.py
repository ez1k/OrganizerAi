"""Dashboard summary endpoint."""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.services.summary_service import build_user_summary

logger = logging.getLogger(__name__)
router = APIRouter(tags=["summary"])


@router.get("/summary")
def get_summary(
    user_id: str = "local-user",
    days: int = Query(default=30, ge=7, le=90),
):
    """Return real user activity and OrganizerAI usage statistics."""
    try:
        return build_user_summary(user_id, days=days)
    except Exception as exc:
        logger.exception("Failed to build dashboard summary for user_id=%s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Nie udało się przygotować podsumowania.",
        ) from exc
