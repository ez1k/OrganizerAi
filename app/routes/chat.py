from fastapi import APIRouter
from app.schemas import ChatRequest
from app.services.llm_service import ask_llm
from app.services.date_parser import build_event_time
from app.services.google_calendar import create_event
import json

router = APIRouter()


def clean_json(text: str) -> str:
    if not text:
        return ""

    text = text.strip()
    text = text.replace("```json", "").replace("```", "")
    return text


@router.post("/chat")
def chat_endpoint(request: ChatRequest):

    prompt = f"""
    Zamień tekst użytkownika na JSON.
    
    TEKST:
    {request.message}
    
    ZASADY:
    - ZWRÓĆ WYŁĄCZNIE JSON
    - NIE dodawaj żadnego tekstu
    - JEŚLI NIE POTRAFISZ → ZWRÓĆ PUSTY OBIEKT
    
    FORMAT:
    {{
      "title": "string",
      "date_hint": "np. jutro 18:00, piątek 15",
      "duration_minutes": 60,
      "description": "string"
    }}
    """

    try:
        response = ask_llm(prompt)

        cleaned = clean_json(response)

        if not cleaned or not cleaned.strip().startswith("{"):
            return {
                "status": "error",
                "message": "LLM did not return valid JSON",
                "raw": cleaned
            }

        data = json.loads(cleaned)

        # 🔥 safety fallback
        if not data:
            return {
                "status": "error",
                "message": "Empty JSON from LLM",
                "raw": cleaned
            }

        start, end = build_event_time(
            data.get("date_hint", ""),
            data.get("duration_minutes", 60)
        )

        event = {
            "title": data.get("title", "No title"),
            "description": data.get("description", ""),
            "start": start.isoformat(),
            "end": end.isoformat()
        }

        link = create_event(event)

        return {
            "status": "ok",
            "event": event,
            "calendar_link": link
        }

    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "Invalid JSON from LLM",
            "raw": cleaned
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }