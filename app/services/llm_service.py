"""LLM adapter for semantic interpretation of OrganizerAI messages."""

import json
import logging
from time import perf_counter

import requests

from app.services.database import find_learning_examples, format_learning_examples
from app.services.turn_timing import record_component

logger = logging.getLogger(__name__)
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral"

SYSTEM_PROMPT = """
Jesteś modułem NLU dla aplikacji do planowania aktywności.
Twoim zadaniem jest WYŁĄCZNIE rozpoznać znaczenie wiadomości i wyodrębnić dane.
NIE decydujesz o stanie dialogu, potwierdzeniu ani wykonaniu operacji — robi to deterministyczny backend.
Zwracasz wyłącznie poprawny JSON i nie wymyślasz brakujących danych.

Wybierz jedną operację semantyczną:
- create: użytkownik chce dodać/zaplanować/umówić/wrzucić aktywność do kalendarza,
- search: użytkownik pyta o własny kalendarz lub chce sprawdzić wydarzenia,
- delete: użytkownik chce usunąć/skasować/wywalić wydarzenie,
- external_search: pytanie dotyczy informacji spoza kalendarza, np. pogody, kina, filmu, repertuaru, wiadomości,
- chat: zwykła rozmowa/small-talk,
- cancelled: wyraźne anulowanie bieżącej operacji.

DANE:
- CREATE -> event: title, date_hint, time_hint, duration_minutes, description.
- SEARCH/DELETE -> search: title, date_hint, time_hint, range_type, range_days.
- Dla SEARCH/DELETE nie wkładaj kryteriów do event.
- Przy DELETE nigdy nie wymyślaj event_id ani selected_event_id.

ZASADY EKSTRAKCJI:
1. Używaj wyłącznie informacji z bieżącej wiadomości, historii i AKTUALNEGO STANU.
2. Nigdy nie zakładaj domyślnie „dzisiaj”, konkretnej godziny ani czasu trwania.
3. „18”, „o 18”, „18:00” oznaczają time_hint; konkretną godzinę normalizuj do HH:MM.
4. „90 minut”=90, „godzinę”=60, „pół godziny”=30, „półtorej godziny”=90, „dwie godziny”=120.
5. „o 12 półtorej godziny” oznacza time_hint="12:00" oraz duration_minutes=90, nigdy 12:30.
6. „rano”, „po południu”, „wieczorem” nie są dokładną godziną. Nie zapisuj ich jako time_hint, jeśli brak konkretnej godziny.
7. Jeśli daty nie podano, nie dodawaj „dziś”.
8. Dni tygodnia zwracaj kanonicznie: poniedziałek, wtorek, środa, czwartek, piątek, sobota, niedziela.
9. Wyodrębnij sensowny title aktywności, np. „pouczyć się” -> tytuł związany z nauką.
10. Jeśli użytkownik zmienia temat mimo istniejącego draftu, klasyfikuj nową wiadomość według jej własnego znaczenia.
11. Jeśli użytkownik poprawia aktywny CREATE, np. „jednak o 18:30”, zwróć podaną korektę i zachowaj semantykę operacji create.
12. W reply nie twierdź, że operacja została już wykonana.

ZWERYFIKOWANE PRZYKŁADY z retrieval są tylko wzorcami semantycznymi. Nie kopiuj z nich wartości,
których nie ma w bieżącej wiadomości/stanie. Jeśli zawierają status, ignoruj go — status wylicza backend.

FORMAT:
{
  "reply": "krótka odpowiedź po polsku",
  "operation": "create | search | delete | external_search | chat | cancelled",
  "event": {"title": "string", "date_hint": "string", "time_hint": "string", "duration_minutes": 90, "description": "string"},
  "search": {"title": "string", "date_hint": "string", "time_hint": "string", "range_type": "next_days | this_week", "range_days": 14}
}
Pola event/search mogą być częściowe. Pomijaj wartości, których nie znasz.
"""


# Minimal semantic few-shots. They are intentionally different from the frozen
# NLP evaluation utterances and do not teach dialog status/policy.
STATIC_FEW_SHOT_MESSAGES = [
    {
        "role": "user",
        "content": "wpisz mi jutro o 8 półtorej godziny pisania pracy",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Rozumiem dane wydarzenia.",
                "operation": "create",
                "event": {
                    "title": "pisanie pracy",
                    "date_hint": "jutro",
                    "time_hint": "08:00",
                    "duration_minutes": 90,
                },
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "jutro wieczorem chcę przez godzinę robić porządki",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Rozumiem podane dane.",
                "operation": "create",
                "event": {
                    "title": "porządki",
                    "date_hint": "jutro",
                    "duration_minutes": 60,
                },
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "dodaj godzinę medytacji o 21",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Rozumiem podane dane.",
                "operation": "create",
                "event": {
                    "title": "medytacja",
                    "time_hint": "21:00",
                    "duration_minutes": 60,
                },
            },
            ensure_ascii=False,
        ),
    },
]


def ask_llm(
    message: str,
    history: list[dict],
    draft_event: dict | None = None,
    user_id: str = "local-user",
) -> dict:
    """Ask Ollama for semantic NLU output.

    The model extracts operation and semantic slots. Dialog status/policy is
    intentionally applied later by app.services.dialog_policy.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(STATIC_FEW_SHOT_MESSAGES)

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

    started_at = perf_counter()
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 300},
            },
            timeout=120,
        )
        response.raise_for_status()
    finally:
        record_component("llm", round((perf_counter() - started_at) * 1000))

    result = response.json().get("message", {}).get("content", "")
    if not result.strip():
        raise ValueError("Empty response from Ollama")

    parsed = json.loads(result)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid structured response from Ollama")
    parsed.setdefault("reply", "")
    return parsed
