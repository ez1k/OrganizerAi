from fastapi import APIRouter
from app.schemas import ChatRequest
from app.services.llm_service import ask_llm
from app.services.date_parser import build_event_time
from app.services.google_calendar import create_event
import json

router = APIRouter()


def clean_json(text: str):
    return text.strip().replace("```json", "").replace("```", "")


@router.post("/chat")
def chat_endpoint(request: ChatRequest):

    prompt = f"""
Wyciągnij dane z tekstu:

{request.message}

ZWRÓĆ WYŁĄCZNIE POPRAWNY JSON.
BEZ TEKSTU PRZED I PO.
JEŚLI NIE WIESZ → ZWRÓĆ PUSTY OBIEKT 
{{
  "title": "string",
  "date_hint": "np. jutro o 18, piątek 15:00",
  "duration_minutes": 60,
  "description": "string"
}}

Tylko JSON.
"""

    response = ask_llm(prompt)
    cleaned = clean_json(response)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "Invalid JSON from LLM",
            "raw": cleaned
        }

    start, end = build_event_time(
        data["date_hint"],
        data.get("duration_minutes", 60)
    )

    event = {
        "title": data["title"],
        "description": data["description"],
        "start": start.isoformat(),
        "end": end.isoformat()
    }

    link = create_event(event)

    return {
        "status": "ok",
        "event": event,
        "calendar_link": link
    }