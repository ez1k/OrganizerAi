import json
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral"

SYSTEM_PROMPT = """
Jesteś modułem rozumienia języka dla aplikacji do planowania aktywności.
Nie jesteś właścicielem logiki rozmowy i NIGDY nie zapisujesz wydarzenia.
Twoim zadaniem jest wyłącznie odczytać dane z bieżącej wiadomości oraz uzupełnić lub zmienić istniejący draft.

Dane wydarzenia:
- title: nazwa aktywności
- date_hint: dzień i godzina w języku naturalnym
- duration_minutes: czas trwania
- description: opcjonalny opis

ZASADY EKSTRAKCJI:
1. Wykorzystaj wszystkie informacje z bieżącej wiadomości. Nie pytaj ponownie o informację, którą użytkownik już podał.
2. Korzystaj także z AKTUALNEGO DRAFTU i historii rozmowy.
3. Jeśli użytkownik doprecyzowuje informację, zmień tylko odpowiednie pole draftu. Np. "o 19" zmienia godzinę, a nie nazwę ani dzień.
4. "godzinę" / "o której" oznacza brakującą godzinę tylko wtedy, gdy draft rzeczywiście jej nie zawiera.
5. "60 min", "godzinę", "1,5 godziny" itp. przelicz na duration_minutes.
6. "tak", "potwierdzam", "dodaj", "zapisz" są potwierdzeniami, ale backend obsługuje je deterministycznie. Możesz zwrócić ready_for_confirmation; NIE zapisuj niczego.
7. Nie wymyślaj brakujących danych.
8. Gdy brakuje wymaganej informacji, status ma być needs_input i event może zawierać częściowy draft.
9. Gdy title, dzień, godzina i duration_minutes są kompletne, status ma być ready_for_confirmation.
10. Odpowiedź użytkownika ma być po polsku i krótka. Jeśli komplet danych jest dostępny, podsumuj je i poproś o potwierdzenie.
11. ZWRÓĆ WYŁĄCZNIE poprawny JSON, bez markdownu.

FORMAT:
{
  "reply": "wiadomość dla użytkownika",
  "status": "needs_input | ready_for_confirmation | cancelled | chat",
  "event": {
    "title": "string",
    "date_hint": "string",
    "duration_minutes": 60,
    "description": "string"
  }
}

Event może być częściowy podczas zbierania danych.
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
        context = f"\nAKTUALNY DRAFT WYDARZENIA:\n{json.dumps(draft_event, ensure_ascii=False)}\n"

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
            "options": {
                "temperature": 0.1,
                "num_predict": 300
            }
        },
        timeout=120
    )
    response.raise_for_status()

    data = response.json()
    result = data.get("message", {}).get("content", "")
    if not result.strip():
        raise ValueError("Empty response from Ollama")

    parsed = json.loads(result)
    if not isinstance(parsed, dict) or "reply" not in parsed or "status" not in parsed:
        raise ValueError("Invalid structured response from Ollama")

    return parsed
