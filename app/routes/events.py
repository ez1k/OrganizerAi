from fastapi import APIRouter, HTTPException, Query

from app.services.event_reflection_service import list_event_reflections
from app.services.event_service import get_events
from app.services.google_calendar import list_recent_completed_events

router = APIRouter()


@router.get("/events")
def list_events():
    return get_events()


@router.get("/events/completed")
def list_completed_events(
    user_id: str = "local-user",
    days: int = Query(default=14, ge=1, le=90),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return recently completed Calendar events with reflection state."""
    try:
        events = list_recent_completed_events(days=days, max_results=limit)
        reflected_ids = {
            str(item.get("calendar_event_id") or "")
            for item in list_event_reflections(user_id, limit=100)
        }
        return {
            "events": [
                {**event, "reflected": str(event.get("id") or "") in reflected_ids}
                for event in events
            ]
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Nie udało się pobrać zakończonych wydarzeń.",
        ) from exc
