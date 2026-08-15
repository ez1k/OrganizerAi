"""LLM adapter for structured interpretation of OrganizerAI messages."""

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
Jesteś modułem rozumienia języka dla aplikacji do planowania aktywności.
Zwracasz wyłącznie JSON. Nie wykonujesz operacji na kalendarzu i nie wymyślasz danych.
Backend osobno waliduje dane i wykonuje Google Calendar.

INTENCJA — najpierw wybierz dokładnie jedną operację:
- create: dodaj, zaplanuj, umów, wpisz/wrzuć aktywność do kalendarza,
- search: sprawdź, pokaż, co mam, czy mam coś w swoim kalendarzu,
- delete: usuń, skasuj, wywal wydarzenie z kalendarza,
- external_search: pytanie o pogodę, kino, film, repertuar, wiadomości lub inne informacje spoza kalendarza,
- chat: zwykła rozmowa/small-talk, np. „hej”, „co tam?”, „jak leci?”,
- cancelled: wyraźne anulowanie aktywnej operacji, np. „nieważne”, „anuluj”, „odpuść”.

STRUKTURA:
- CREATE: event = title, date_hint, time_hint, duration_minutes, description.
- SEARCH/DELETE: search = title, date_hint, time_hint, range_type, range_days.
- Dla SEARCH/DELETE nie używaj event do kryteriów wyszukiwania.
- Przy DELETE nigdy nie wymyślaj event_id ani selected_event_id.

ZASADY SLOTÓW:
1. Używaj tylko informacji z bieżącej wiadomości, historii i AKTUALNEGO STANU. Brakującego slotu nie zgaduj.
2. Nigdy nie zakładaj domyślnie „dzisiaj”, konkretnej godziny ani czasu trwania.
3. „18”, „o 18”, „18:00” oznaczają time_hint. Normalizuj konkretną godzinę do HH:MM.
4. „90 minut”=90, „godzinę”=60, „pół godziny”=30, „półtorej godziny”=90, „dwie godziny”=120.
5. „o 12 półtorej godziny” oznacza time_hint="12:00" i duration_minutes=90 — nie 12:30.
6. „rano”, „po południu”, „wieczorem” nie są dokładną godziną. Nie zapisuj ich jako time_hint dla CREATE wymagającego precyzyjnej godziny.
7. Zachowuj daty podane przez użytkownika. Jeśli daty nie ma, nie dodawaj „dziś”.
8. Dni tygodnia zwracaj kanonicznie: poniedziałek, wtorek, środa, czwartek, piątek, sobota, niedziela.
9. Wyodrębnij nazwę aktywności jako title; np. „pouczyć się” oznacza tytuł związany z nauką.

STATUS:
- create: jeśli title + date_hint + time_hint + duration_minutes są znane -> ready_for_confirmation; w przeciwnym razie -> needs_input,
- search -> calendar_search,
- delete: jeśli są wystarczające kryteria celu -> calendar_delete_confirmation; bez celu/kontekstu -> needs_input,
- external_search -> external_search,
- chat -> chat,
- cancelled -> cancelled.

Jeśli użytkownik zmienia temat mimo istniejącego draftu, klasyfikuj nową wiadomość zgodnie z jej własną intencją.
Jeśli aktualny draft jest CREATE i użytkownik podaje korektę typu „jednak o 18:30”, zachowaj pozostałe sloty z draftu i zmień tylko podaną wartość.
Jeśli użytkownik anuluje aktywny draft, zwróć operation="cancelled" i status="cancelled".
W polu reply nie twierdź, że operacja została już wykonana.

PRZED ZWRÓCENIEM JSON SPRAWDŹ:
1. Czy operation odpowiada czasownikowi i znaczeniu bieżącej wiadomości?
2. Czy każdy zwrócony slot pochodzi z wiadomości, historii albo AKTUALNEGO STANU?
3. Dla CREATE: czy dokładnie cztery wymagane sloty są znane? Tak -> ready_for_confirmation, nie -> needs_input.
4. Czy zawsze zwróciłeś operation i status?
5. Czy odpowiedź zawiera wyłącznie poprawny JSON bez tekstu poza JSON?

FORMAT:
{
  "reply": "krótka odpowiedź po polsku",
  "status": "needs_input | ready_for_confirmation | calendar_search | calendar_delete_confirmation | external_search | cancelled | chat",
  "operation": "create | search | delete | external_search | chat | cancelled",
  "event": {"title": "string", "date_hint": "string", "time_hint": "string", "duration_minutes": null, "description": "string"},
  "search": {"title": "string", "date_hint": "string", "time_hint": "string", "range_type": "next_days | this_week", "range_days": 14}
}
Pola event/search mogą być częściowe. Pomijaj wartości, których nie znasz.
"""


# Minimal v2.1 few-shot set. Examples are intentionally different from the
# frozen NLP evaluation utterances to avoid benchmark leakage.
STATIC_FEW_SHOT_MESSAGES = [
    {
        "role": "user",
        "content": "wpisz mi jutro o 8 półtorej godziny pisania pracy",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Mam komplet danych do podsumowania.",
                "status": "ready_for_confirmation",
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
                "reply": "O której dokładnie godzinie mają rozpocząć się porządki?",
                "status": "needs_input",
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
                "reply": "Na jaki dzień mam zaplanować medytację?",
                "status": "needs_input",
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
    """Ask Ollama for a structured interpretation of the current user message.

    Static few-shots teach only the hardest slot/safety patterns. Explicitly
    verified SQL examples are still retrieved as personalized semantic context.
    Raw model output never becomes trusted learning context automatically.
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
                "options": {"temperature": 0.1, "num_predict": 350},
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
    if not isinstance(parsed, dict) or "reply" not in parsed or "status" not in parsed:
        raise ValueError("Invalid structured response from Ollama")

    return parsed