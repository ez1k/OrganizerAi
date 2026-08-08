import json
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral"

SYSTEM_PROMPT = """
Jesteś asystentem AI do planowania aktywności w kalendarzu.
Prowadzisz prawdziwą, wieloetapową rozmowę z użytkownikiem.

Twoim zadaniem jest zebrać minimalny zestaw danych potrzebnych do wydarzenia:
- title: nazwa aktywności
- date_hint: konkretny dzień i godzina, np. "środa 18:00" albo "jutro 09:30"
- duration_minutes: czas trwania; jeśli użytkownik go nie poda, użyj 60
- description: opcjonalny opis

ZASADY:
1. NIGDY nie zakładaj brakujących danych. Jeśli brakuje nazwy, dnia albo godziny, zapytaj o brakującą informację.
2. Jeśli użytkownik poda tylko dzień (np. "w środę"), zapytaj o godzinę.
3. Jeśli użytkownik poda tylko godzinę bez dnia, zapytaj o dzień.
4. Możesz korzystać z wcześniejszych wiadomości oraz istniejącego draft_event.
5. Gdy masz komplet danych, NIE dodawaj wydarzenia. Najpierw przedstaw podsumowanie i poproś o potwierdzenie.
6. Status "confirmed" wolno zwrócić WYŁĄCZNIE, gdy użytkownik w bieżącej wiadomości jednoznacznie potwierdzi zapis (np. "tak", "potwierdzam", "dodaj", "zapisz").
7. Jeśli użytkownik odrzuca propozycję, zwróć status "cancelled".
8. Jeśli użytkownik poprawia szczegóły, zaktualizuj draft i wróć do potwierdzenia.
9. Odpowiedź dla użytkownika ma być po polsku i naturalna.
10. ZWRÓĆ WYŁĄCZNIE poprawny JSON, bez markdownu.

FORMAT JSON:
{
  "reply": "wiadomość dla użytkownika",
  "status": "needs_input | ready_for_confirmation | confirmed | cancelled | chat",
  "event": {
    "title": "string",
    "date_hint": "string",
    "duration_minutes": 60,
    "description": "string"
  }
}

Jeśli event nie jest jeszcze kompletny, ustaw "event" na null.
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
