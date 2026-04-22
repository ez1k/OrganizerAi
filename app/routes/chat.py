from fastapi import APIRouter
from app.schemas import ChatRequest
from app.services.llm_service import ask_llm
from app.services.event_service import save_event
import json

router = APIRouter()


def clean_json(text: str) -> str:
    if not text:
        raise ValueError("Empty response from LLM")

    text = text.strip()
    text = text.replace("```json", "").replace("```", "")

    return text


@router.post("/chat")
def chat_endpoint(request: ChatRequest):

    prompt = f"""
Zamień tekst na JSON wydarzenia.

Tekst:
{request.message}

ZWRÓĆ TYLKO JSON:

{{
  "title": "string",
  "start": "YYYY-MM-DD HH:MM",
  "end": "YYYY-MM-DD HH:MM",
  "description": "string"
}}

NIE dodawaj żadnego tekstu poza JSON.
"""

    response = ask_llm(prompt)

    try:
        response = clean_json(response)

        # safety check
        if not response.strip():
            return {"status": "error", "message": "Empty LLM response"}

        event = json.loads(response)

        save_event(event)

        return {"status": "ok", "event": event}

    except json.JSONDecodeError as e:
        return {
            "status": "error",
            "message": "Invalid JSON from LLM",
            "raw": response
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }