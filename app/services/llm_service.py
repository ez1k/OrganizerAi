"""LLM adapter for structured interpretation of OrganizerAI messages."""

import json
import logging

import requests

from app.services.database import find_learning_examples, format_learning_examples

logger = logging.getLogger(__name__)
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral"

SYSTEM_PROMPT = """
Jesteś modułem rozumienia języka dla aplikacji do planowania aktywności.
NIE wykonujesz operacji na kalendarzu i NIE wymyślasz danych, których użytkownik nie podał.
Backend wykonuje operacje na podstawie Twojego JSON.

Możliwe operacje:
- create: dodaj nowe wydarzenie
- search: sprawdź/pokaż wydarzenia z kalendarza użytkownika
- delete: usuń istniejące wydarzenie
- external_search: pytanie o informacje spoza kalendarza
- chat: zwykła rozmowa
- cancelled: anulowanie bieżącej operacji

Dla CREATE dane wydarzenia: title, date_hint, time_hint, duration_minutes, description.
Dla SEARCH/DELETE użyj search: title, date_hint, time_hint, range_type, range_days.

ZASADY:
1. Wykorzystaj wszystkie informacje z bieżącej wiadomości i aktualnego draftu.
2. "18", "o 18", "18:00" oznaczają time_hint, NIGDY duration_minutes.
3. "18 min", "60 min", "godzinę", "1,5 godziny" oznaczają duration_minutes.
4. Jeśli liczba nie ma jednostki i opisuje porę dnia, traktuj ją jako time_hint.
5. Nigdy nie ustawiaj domyślnie 18:00.
6. Nie wymyślaj dnia, godziny, czasu trwania ani lokalizacji.
7. "dodaj", "zaplanuj", "umów" oznaczają CREATE.
8. "sprawdź", "co mam", "co jest", "pokaż" oznaczają SEARCH kalendarza.
9. Pytania o repertuar, kino, film, pogodę itp. są EXTERNAL_SEARCH.
10. "usuń", "skasuj", "wywal" oznaczają DELETE.
11. "ten", "ten drugi", "poprzedni", "go" mogą odnosić się do poprzednich wyników; backend je przechowuje.
12. Przy DELETE nie wymyślaj event_id. Zwróć kryteria search.
13. SEARCH i EXTERNAL_SEARCH nie wymagają potwierdzenia.
14. DELETE i CREATE wymagają potwierdzenia backendu.
15. Jeśli użytkownik pyta o coś niezależnego od poprzedniego draftu, nie kontynuuj starego draftu.
16. Odpowiedź po polsku i krótka.
17. Jeśli dostajesz ZWERYFIKOWANE PRZYKŁADY, traktuj je jako wzorce semantyczne podobnych wypowiedzi. Nie kopiuj z nich dat, godzin, tytułów ani innych wartości, których nie ma w bieżącej wiadomości lub aktualnym stanie.
18. ZWRÓĆ WYŁĄCZNIE poprawny JSON.

FORMAT:
{
  "reply": "krótka odpowiedź",
  "status": "needs_input | ready_for_confirmation | calendar_search | calendar_delete_confirmation | external_search | cancelled | chat",
  "operation": "create | search | delete | external_search | chat",
  "event": {"title": "string", "date_hint": "string", "time_hint": "string", "duration_minutes": 60, "description": "string"},
  "search": {"title": "string", "date_hint": "string", "time_hint": "string", "range_type": "next_days | this_week", "range_days": 14}
}
Pola event/search mogą być częściowe.
"""


def ask_llm(
    message: str,
    history: list[dict],
    draft_event: dict | None = None,
    user_id: str = "local-user",
) -> dict:
    """Ask Ollama for a structured interpretation of the current user message.

    Only explicitly verified SQL examples are read here as few-shot context.
    Writes are handled by the backend/feedback flow so raw model output cannot
    silently become trusted training context.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    try:
        examples = find_learning_examples(user_id, message, limit=3)
    except Exception:
        logger.exception("Failed to load verified learning examples for user_id=%s", user_id)
        examples = []

    logger.info("LLM verified learning examples user_id=%s count=%s", user_id, len(examples))
    examples_context = format_learning_examples(examples)

    for item in history[-20:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    context = ""
    if draft_event:
        context = f"\nAKTUALNY STAN:\n{json.dumps(draft_event, ensure_ascii=False)}\n"

    messages.append(
        {
            "role": "user",
            "content": f"{examples_context}{context}\nNOWA WIADOMOŚĆ UŻYTKOWNIKA:\n{message}",
        }
    )

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 350},
        },
        timeout=120,
    )
    response.raise_for_status()

    result = response.json().get("message", {}).get("content", "")
    if not result.strip():
        raise ValueError("Empty response from Ollama")

    parsed = json.loads(result)
    if not isinstance(parsed, dict) or "reply" not in parsed or "status" not in parsed:
        raise ValueError("Invalid structured response from Ollama")

    return parsed
