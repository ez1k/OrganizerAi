"""NLP analysis for natural-language post-event reflections.

The model interprets how the user experienced a completed activity. It does not
schedule reminders or create calendar events. Those decisions remain explicit,
deterministic application actions performed only after user consent.
"""

from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

import requests

from app.services.llm_service import MODEL, OLLAMA_URL

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = {"positive", "neutral", "negative", "mixed"}
VALID_CONFIDENCE = {"high", "medium", "low"}

REFLECTION_SYSTEM_PROMPT = """
Jesteś modułem NLP analizującym krótką opinię użytkownika o ZAKOŃCZONYM wydarzeniu lub aktywności.
Nie planujesz wydarzeń, nie tworzysz przypomnień i nie podejmujesz decyzji za użytkownika.
Zwracasz wyłącznie poprawny JSON.

Oceń:
- sentiment: positive, neutral, negative albo mixed,
- rating: liczba 1-5 tylko wtedy, gdy ocena jest podana wprost albo ton wypowiedzi daje wyraźną podstawę do przybliżonej oceny; przy niejednoznaczności null,
- worth_repeating: true, jeśli wypowiedź wyraźnie sugeruje chęć/wartość powtórzenia; false, jeśli wyraźnie odrzuca powtórzenie; w pozostałych przypadkach null,
- confidence: high, medium albo low,
- summary: bardzo krótki opis po polsku, bez dodawania faktów spoza wypowiedzi.

Ważne:
1. "Było super, dobrze mi zrobiło" -> positive; nie oznacza automatycznie zgody na przypomnienie.
2. "Męczące, ale warto" może być mixed i worth_repeating=true.
3. "Nie chcę tego więcej" -> worth_repeating=false.
4. Nie wymyślaj przyczyn, emocji ani preferencji, których użytkownik nie wyraził.
5. Jeśli użytkownik poda ocenę np. "4/5", zachowaj dokładnie tę wartość.

FORMAT:
{
  "sentiment": "positive | neutral | negative | mixed",
  "rating": 1,
  "worth_repeating": true,
  "confidence": "high | medium | low",
  "summary": "krótki opis"
}
Dla nieznanych rating/worth_repeating użyj null.
"""


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _explicit_rating(feedback_text: str) -> int | None:
    """Extract an explicitly stated 1-5 rating so it can override model drift."""
    text = _normalize_text(feedback_text).lower()
    patterns = (
        r"\b([1-5])\s*/\s*5\b",
        r"\b([1-5])\s+na\s+5\b",
        r"\b(?:ocena|oceniam|daję|daje)\s*[:=-]?\s*([1-5])\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def sanitize_reflection_analysis(feedback_text: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the model output and apply small deterministic grounding rules."""
    if not isinstance(raw, dict):
        raise ValueError("Analiza refleksji musi być obiektem JSON.")

    sentiment = str(raw.get("sentiment") or "").strip().lower()
    if sentiment not in VALID_SENTIMENTS:
        raise ValueError("Model zwrócił nieprawidłowy sentiment.")

    rating = raw.get("rating")
    if rating not in (None, ""):
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = None
        if rating is not None and not 1 <= rating <= 5:
            rating = None

    explicit_rating = _explicit_rating(feedback_text)
    if explicit_rating is not None:
        rating = explicit_rating

    worth_repeating = raw.get("worth_repeating")
    if not isinstance(worth_repeating, bool):
        worth_repeating = None

    confidence = str(raw.get("confidence") or "medium").strip().lower()
    if confidence not in VALID_CONFIDENCE:
        confidence = "medium"

    summary = _normalize_text(raw.get("summary"))[:500]
    if not summary:
        summary = "Brak jednoznacznego podsumowania."

    return {
        "sentiment": sentiment,
        "rating": rating,
        "worth_repeating": worth_repeating,
        "confidence": confidence,
        "summary": summary,
    }


def analyze_event_reflection(feedback_text: str) -> dict[str, Any]:
    """Interpret one natural-language post-event reflection with local Mistral."""
    text = _normalize_text(feedback_text)
    if not text:
        raise ValueError("Treść opinii nie może być pusta.")

    started_at = perf_counter()
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 180},
        },
        timeout=120,
    )
    llm_latency_ms = max(0, round((perf_counter() - started_at) * 1000))
    response.raise_for_status()

    content = response.json().get("message", {}).get("content", "")
    if not str(content).strip():
        raise ValueError("Model zwrócił pustą analizę refleksji.")

    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Model zwrócił niepoprawny JSON refleksji.") from exc

    analysis = sanitize_reflection_analysis(text, raw)
    analysis["llm_latency_ms"] = llm_latency_ms
    return analysis
