from fastapi import APIRouter
from app.schemas import ChatRequest
from app.services.llm_service import ask_llm
from app.services.date_parser import build_datetime
import json
from datetime import timedelta

router = APIRouter()


def clean_json(text: str):
    return text.strip().replace("```json", "").replace("```", "")


@router.post("/chat")
def chat_endpoint(request: ChatRequest):

    prompt = f"""
Wyciągnij dane z tekstu.

TEKST:
{request.message}

Zwróć JSON:

{{
  "title": "string",
  "date_hint": "np. jutro wieczorem, dziś 18:00",
  "duration_minutes": 60,
  "description": "string"
}}

Tylko JSON.
"""

    response = ask_llm(prompt)
    data = json.loads(clean_json(response))

    start = build_datetime(data["date_hint"])
    end = start + timedelta(minutes=data.get("duration_minutes", 60))

    event = {
        "title": data["title"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "description": data["description"]
    }

    return {
        "status": "ok",
        "event": event
    }