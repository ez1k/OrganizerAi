from fastapi import APIRouter
from app.schemas import ChatRequest
from app.services.llm_service import ask_llm
from app.services.event_service import save_event
import json

router = APIRouter()


def clean_json(text: str) -> str:
    text = text.strip()
    text = text.replace("```json", "").replace("```", "")
    return text


@router.post("/chat")
def chat_endpoint(request: ChatRequest):

    prompt = f"""
Jesteś asystentem kalendarza.

Zamień tekst użytkownika na JSON wydarzenia.

TEKST:
{request.message}

ZWRÓĆ WYŁĄCZNIE JSON:

{{
  "title": "string",
  "start": "YYYY-MM-DD HH:MM",
  "end": "YYYY-MM-DD HH:MM",
  "description": "string"
}}

Jeśli brak daty, załóż logicznie.
"""

    try:
        response = ask_llm(prompt)
        response = clean_json(response)

        event = json.loads(response)

        save_event(event)

        return {
            "status": "ok",
            "event": event
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "raw": response if "response" in locals() else None
        }