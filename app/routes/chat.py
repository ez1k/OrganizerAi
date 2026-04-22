from fastapi import APIRouter
from app.routes.tasks import chat
from app.services.llm_service import ask_llm
from app.services.event_service import save_event
import json

router = APIRouter()

@router.post("/chat")
def chat(request: chat):
    prompt = f"""
Zamień tekst na JSON wydarzenia:

Tekst: {request.message}

Zwróć WYŁĄCZNIE JSON:
{{
    "title": "...",
    "start": "YYYY-MM-DD HH:MM",
    "end": "YYYY-MM-DD HH:MM",
    "description": "..."
}}
"""

    try:
        response = ask_llm(prompt)
        event = json.loads(response)

        save_event(event)

        return {"status": "ok", "event": event}

    except Exception as e:
        return {"status": "error", "message": str(e)}