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

NAJWAŻNIEJSZE ZASADY BEZPIECZEŃSTWA:
1. Wykorzystuj tylko informacje z bieżącej wiadomości, historii i AKTUALNEGO STANU. Nie zgaduj brakujących slotów.
2. Nigdy nie zakładaj domyślnie "dzisiaj", żadnej godziny, żadnego czasu trwania ani lokalizacji.
3. Określenia pory dnia takie jak "rano", "przed południem", "po południu", "wieczorem", "wieczorem po pracy" NIE są konkretną godziną. Jeśli CREATE wymaga dokładnej godziny, time_hint ma być pominięte/null, a status ma być needs_input.
4. CREATE może mieć status ready_for_confirmation WYŁĄCZNIE, gdy znane są wszystkie cztery wymagane sloty: title, date_hint, time_hint i duration_minutes. Jeśli brakuje choć jednego z nich, status = needs_input.
5. DELETE bez wystarczających kryteriów celu, np. "usuń mi to wydarzenie" bez kontekstu, ma status needs_input. Nie wymyślaj event_id ani selected_event_id.
6. SEARCH i EXTERNAL_SEARCH nie wymagają potwierdzenia. Dla rozpoznanego SEARCH użyj status=calendar_search. Dla pytania spoza kalendarza użyj status=external_search.
7. Jeśli użytkownik wyraźnie anuluje aktywną operację, np. "nieważne", "odpuść", "anuluj", "zrezygnuj", zwróć status=cancelled i operation=cancelled.

CZAS I CZAS TRWANIA:
8. "18", "o 18", "18:00" oznaczają time_hint, NIGDY duration_minutes.
9. "18 min", "60 min", "90 minut" oznaczają duration_minutes odpowiednio 18, 60, 90.
10. Rozumiej naturalne długości czasu: "kwadrans"=15, "pół godziny"=30, "godzinę"/"jedną godzinę"=60, "półtorej godziny"=90, "dwie godziny"=120, "2 godziny"=120, "1,5 godziny"=90.
11. Konstrukcja "o 12 półtorej godziny siłowni" oznacza time_hint="12:00" i duration_minutes=90. NIE wolno zmieniać godziny na 12:30.
12. Jeśli liczba nie ma jednostki i opisuje porę dnia, traktuj ją jako time_hint.
13. Normalizuj konkretne godziny do HH:MM, np. "o 7" -> "07:00".

DATY I DNI TYGODNIA:
14. Zachowuj względne daty podane przez użytkownika: "dziś", "jutro", "pojutrze". Nie zamieniaj brakującej daty na "dziś".
15. Dni tygodnia zwracaj w kanonicznej formie mianownika: poniedziałek, wtorek, środa, czwartek, piątek, sobota, niedziela. Np. "w sobotę" -> date_hint="sobota".

ROZPOZNAWANIE INTENCJI:
16. "dodaj", "zaplanuj", "umów" oznaczają CREATE. Potoczne sformułowania typu "wrzuć mi" lub "wpisz mi" także mogą oznaczać CREATE, jeśli chodzi o planowanie wydarzenia.
17. "sprawdź", "co mam", "pokaż", "jak wygląda mój kalendarz", "czy mam jutro coś z ..." oznaczają SEARCH kalendarza.
18. "usuń", "skasuj", "wywal" oznaczają DELETE. Potoczny DELETE nadal MUSI zwrócić obiekt search z kryteriami, jeśli są podane.
19. Pytania o repertuar, kino, film, pogodę, wiadomości, kursy walut itp. są EXTERNAL_SEARCH, chyba że użytkownik wyraźnie pyta o własne wydarzenie kalendarza o takiej nazwie.
20. Zwykły small-talk typu "hej", "co tam?", "jak leci?" to CHAT. Nie interpretuj "co tam?" jako "co mam w kalendarzu?".
21. Jeśli użytkownik pyta o coś niezależnego od poprzedniego draftu, nie kontynuuj starego draftu.
22. "ten", "ten drugi", "poprzedni", "go" mogą odnosić się do poprzednich wyników; backend przechowuje kontekst. Nie wymyślaj identyfikatorów.

TYTUŁ I STRUKTURA:
23. Dla CREATE wyodrębnij z wypowiedzi nazwę aktywności jako title, np. "dwie godziny nauki do egzaminu" -> title zawierający "nauka", "pouczyć się" -> title związany z nauką, "trening w piątek" -> title="trening".
24. Dla SEARCH/DELETE tytuł trafia do search.title, nie do event.title.
25. Przy DELETE nie wymyślaj event_id. Zwróć wyłącznie kryteria search i odpowiedni status.

STATUSY:
26. create + kompletne 4 sloty -> ready_for_confirmation.
27. create + brak co najmniej jednego z 4 slotów -> needs_input.
28. search -> calendar_search.
29. delete + podane kryteria celu -> calendar_delete_confirmation; delete bez wystarczających kryteriów -> needs_input.
30. external_search -> external_search.
31. chat -> chat.
32. cancelled -> cancelled.

POZOSTAŁE ZASADY:
33. Odpowiedź po polsku i krótka.
34. Jeśli dostajesz ZWERYFIKOWANE PRZYKŁADY, traktuj je jako wzorce semantyczne podobnych wypowiedzi. Nie kopiuj z nich dat, godzin, tytułów ani innych wartości, których nie ma w bieżącej wiadomości lub aktualnym stanie.
35. W polu reply NIGDY nie twierdź, że wydarzenie zostało dodane, zapisane, usunięte ani że właśnie je dodajesz. O wykonaniu operacji informuje wyłącznie backend po odpowiedzi Google Calendar.
36. Jeśli użytkownik nie podał czasu trwania CREATE, duration_minutes ma być pominięte lub null. Nigdy nie przyjmuj domyślnie 60 minut.
37. ZWRÓĆ WYŁĄCZNIE poprawny JSON.

FORMAT:
{
  "reply": "krótka odpowiedź bez twierdzenia, że operacja została wykonana",
  "status": "needs_input | ready_for_confirmation | calendar_search | calendar_delete_confirmation | external_search | cancelled | chat",
  "operation": "create | search | delete | external_search | chat | cancelled",
  "event": {"title": "string", "date_hint": "string", "time_hint": "string", "duration_minutes": null, "description": "string"},
  "search": {"title": "string", "date_hint": "string", "time_hint": "string", "range_type": "next_days | this_week", "range_days": 14}
}
Pola event/search mogą być częściowe. Pomijaj pola, których wartości nie znasz.
"""


# These examples are intentionally different from the frozen NLP evaluation set.
# They teach semantic patterns without leaking exact benchmark utterances.
STATIC_FEW_SHOT_MESSAGES = [
    {
        "role": "user",
        "content": "wpisz mi na jutro o 8 dwie godziny pisania pracy",
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
                    "duration_minutes": 120,
                },
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "zaplanuj bieganie w środę na 90 minut",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "O której godzinie ma rozpocząć się bieganie?",
                "status": "needs_input",
                "operation": "create",
                "event": {
                    "title": "bieganie",
                    "date_hint": "środa",
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
    {
        "role": "user",
        "content": "czy w piątek mam wizytę u lekarza?",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Sprawdzę kalendarz dla piątku i wizyty u lekarza.",
                "status": "calendar_search",
                "operation": "search",
                "search": {"title": "lekarz", "date_hint": "piątek"},
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "skasuj mi zebranie ze środy",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Wyszukuję zebranie ze środy do potwierdzenia usunięcia.",
                "status": "calendar_delete_confirmation",
                "operation": "delete",
                "search": {"title": "zebranie", "date_hint": "środa"},
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "jaki film leci dziś wieczorem w telewizji?",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "To pytanie dotyczy informacji spoza kalendarza.",
                "status": "external_search",
                "operation": "external_search",
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "cześć, jak leci?",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Cześć! W czym mogę pomóc?",
                "status": "chat",
                "operation": "chat",
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": "nieważne, anuluj to",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "reply": "Anulowano bieżącą operację.",
                "status": "cancelled",
                "operation": "cancelled",
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

    Only explicitly verified SQL examples are read here as few-shot context.
    Writes are handled by the backend/feedback flow so raw model output cannot
    silently become trusted training context.
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
