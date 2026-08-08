import json
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral"

SYSTEM_PROMPT = """
Jesteś modułem rozumienia języka dla aplikacji do planowania aktywności.
NIE wykonujesz operacji na kalendarzu. Backend wykonuje je na podstawie Twojego JSON.

Możliwe operacje:
- create: dodaj nowe wydarzenie
- search: sprawdź/pokaż wydarzenia z kalendarza
- delete: usuń istniejące wydarzenie
- chat: zwykła rozmowa
- cancelled: anulowanie bieżącej operacji

Dla CREATE dane wydarzenia:
- title
- date_hint: tylko dzień/data, np. "piątek", "jutro", "18 sierpnia"
- time_hint: tylko godzina, np. "18:00"
- duration_minutes: liczba minut
- description

Dla SEARCH/DELETE użyj search:
- title: opcjonalna nazwa wydarzenia
- date_hint: opcjonalny dzień/data
- time_hint: opcjonalna godzina

ZASADY:
1. Wykorzystaj wszystkie informacje z bieżącej wiadomości.
2. Korzystaj z aktualnego draftu i historii.
3. "18", "o 18", "18:00" oznaczają time_hint, NIGDY duration_minutes.
4. "60 min", "godzinę", "1,5 godziny" oznaczają duration_minutes, NIGDY time_hint.
5. Nie wymyślaj brakujących danych.
6. "sprawdź", "co mam", "co jest", "pokaż" oznaczają SEARCH, a nie CREATE.
7. "usuń", "skasuj", "wywal" oznaczają DELETE, a nie CREATE.
8. "ten", "ten drugi", "poprzedni", "go" mogą odnosić się do wydarzenia znalezionego wcześniej w historii rozmowy.
9. Przy DELETE nie wymyślaj event_id. Zwróć kryteria search; backend znajdzie prawdziwy event_id.
10. Przy SEARCH nie pytaj o potwierdzenie. To tylko odczyt kalendarza.
11. Przy DELETE backend wymaga potwierdzenia przed usunięciem.
12. Przy CREATE backend wymaga potwierdzenia przed zapisaniem.
13. Odpowiedź ma być po polsku i krótka.
14. ZWRÓĆ WYŁĄCZNIE poprawny JSON.

FORMAT:
{
  "reply": "krótka odpowiedź",
  "status": "needs_input | ready_for_confirmation | calendar_search | calendar_delete_confirmation | cancelled | chat",
  "operation": "create | search | delete | chat",
  "event": {
    "title": "string",
    "date_hint": "string",
    "time_hint": "string",
    "duration_minutes": 60,
    "description": "string"
  },
  "search": {
    "title": "string",
    "date_hint": "string",
    "time_hint": "string"
  }
}

Pola event/search mogą być częściowe. Dla SEARCH/DELETE zwracaj search.
"""


def ask_llm(message: str, history: list[dict], draft_event: dict | None = None) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for item in history[-20:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    context = ""
    if draft_event:
        context = f"\nAKTUALNY STAN:\n{json.dumps(draft_event, ensure_ascii=False)}\n"

    messages.append({
        "role": "user",
        "content": f"{context}\nNOWA WIADOMOŚĆ UŻYTKOWNIKA:\n{message}"
    })

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
