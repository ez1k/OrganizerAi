# OrganizerAI

OrganizerAI to konwersacyjny asystent organizacji czasu napisany w Pythonie. Aplikacja pozwala użytkownikowi rozmawiać po polsku o wydarzeniach, wyszukiwać je w Google Calendar, bezpiecznie tworzyć i usuwać wpisy, oceniać zakończone aktywności oraz ustawiać motywacyjne przypomnienia o czynnościach, które warto powtórzyć.

Projekt wykorzystuje architekturę hybrydową: lokalny model Mistral odpowiada za interpretację semantyczną języka naturalnego, natomiast operacje krytyczne dla bezpieczeństwa kalendarza są walidowane i prowadzone przez deterministyczną logikę backendu.

## Najważniejsze funkcje

- konwersacja w języku polskim,
- CREATE / SEARCH / DELETE dla Google Calendar,
- wieloetapowe doprecyzowanie brakujących danych przed utworzeniem wydarzenia,
- jawne potwierdzenie przed każdą mutacją kalendarza,
- deterministyczne fast-pathy dla jednoznacznych poleceń,
- fallback do lokalnego LLM dla bardziej swobodnych wypowiedzi,
- deterministic grounding dat, godzin, czasu trwania i kryteriów DELETE,
- feedback użytkownika oraz retrieval zweryfikowanych przykładów few-shot,
- pomiar jakości dialogu i czasu działania poszczególnych komponentów,
- refleksja po zakończonym wydarzeniu analizowana przez NLP,
- zapis `sentiment`, `rating` i `worth_repeating`,
- motywacyjne przypomnienia wymagające jawnej zgody użytkownika,
- bezpieczne przejście z reminderu do istniejącego flow CREATE bez automatycznego tworzenia wydarzenia.

## Architektura

```text
Streamlit
  app/frontend/app.py
  app/frontend/motivation_ui.py
        |
        | HTTP / JSON
        v
FastAPI
  app/main.py
        |
        +--> app/routes/chat_flow.py
        |      deterministyczny routing i metryki
        |
        +--> app/routes/chat.py
        |      stan dialogu, walidacja CREATE/SEARCH/DELETE
        |
        +--> app/services/llm_service.py
        |      Ollama / Mistral
        |
        +--> app/services/dialog_policy.py
        |      deterministic grounding
        |
        +--> app/services/google_calendar.py
        |      Google Calendar API
        |
        +--> app/routes/feedback.py
        |      feedback interpretacji
        |
        +--> app/routes/reflections.py
        |      refleksje i motivation reminders
        |
        +--> app/services/reflection_nlp_service.py
        |      analiza opinii po wydarzeniu
        |
        +--> app/services/motivation_time_service.py
        |      deterministyczny parser czasu reminderu
        |
        +--> app/services/database.py
        |      SQL Server / ai_organizer
        |
        +--> app/services/event_reflection_service.py
               persistence refleksji i reminderów
```

Logika kalendarza działa w strefie `Europe/Warsaw`. Techniczne znaczniki czasu w SQL Server są zapisywane w UTC.

## Bezpieczny CREATE

CREATE wymaga kompletu danych:

```text
title
date_hint
time_hint
duration_minutes
```

Jeżeli brakuje informacji, system zachowuje `draft_event` i pyta tylko o brakujące sloty. Wpis nie trafia do Google Calendar, dopóki użytkownik nie zobaczy finalnego podsumowania i nie potwierdzi go jednoznacznie.

Przykład:

```text
Użytkownik: dodaj trening jutro
Asystent: O której godzinie ma się rozpocząć?
Użytkownik: o 18
Asystent: Ile ma trwać wydarzenie?
Użytkownik: 60 min
Asystent: Podsumowanie wydarzenia: ... Czy mam dodać je do Google Calendar?
Użytkownik: tak
```

Jednoznaczne polecenia mogą zostać obsłużone przez deterministyczny fast-path bez wywołania LLM. Bardziej swobodne lub niepełne wypowiedzi przechodzą przez model, ale wynik modelu nadal podlega walidacji backendu.

## Bezpieczeństwo DELETE

DELETE ma bardziej restrykcyjną politykę niż CREATE:

- brak usunięcia przed jednoznacznym potwierdzeniem,
- niejednoznaczne odpowiedzi nie wykonują mutacji,
- przy wielu dopasowaniach wymagany jest wybór konkretnego wydarzenia albo osobna decyzja `usuń wszystkie`,
- testy jednostkowe używają mocków i nie usuwają prawdziwych wydarzeń.

## Feedback i uczenie na zweryfikowanych przykładach

Mechanizm learning feedback loop nie wykonuje fine-tuningu wag Mistrala. Jest to retrieval + few-shot learning na przykładach jawnie zweryfikowanych przez użytkownika.

```text
wiadomość
   ↓
interpretacja systemu
   ↓
👍 / 👎
   ↓
conversation_feedback
   ↓
zweryfikowana korekta
   ↓
learning_examples.corrected = 1
   ↓
retrieval podobnych przykładów
   ↓
przyszły prompt Mistrala
```

Tylko rekordy `corrected = 1` mogą być używane jako kontekst dla modelu. Dane diagnostyczne pozostają poza promptem.

## Refleksja po wydarzeniu

Zakończone wydarzenia z Google Calendar mogą zostać ocenione w Streamlit.

```text
Google Calendar
      ↓
zakończone wydarzenie
      ↓
opinia użytkownika
      ↓
Mistral / reflection NLP
      ↓
sentiment + rating + worth_repeating
      ↓
dbo.event_reflections
```

Model może określić m.in.:

```json
{
  "sentiment": "positive",
  "rating": 5,
  "worth_repeating": true,
  "confidence": "high",
  "summary": "Pozytywna ocena aktywności."
}
```

Jawna ocena użytkownika, np. `5/5`, ma pierwszeństwo przed estymacją modelu. Analiza NLP sama nie tworzy reminderu i nie modyfikuje Google Calendar.

## Motywacyjne przypomnienia

Jeżeli refleksja jest pozytywna lub użytkownik wyraźnie sugeruje chęć powtórzenia aktywności, frontend może zapytać o zgodę na reminder.

```text
refleksja
   ↓
jawna zgoda użytkownika
   ↓
"za 2 tygodnie"
   ↓
deterministyczny parser czasu
   ↓
dbo.motivation_reminders
   ↓
reminder due
   ↓
"Czy chcesz zaplanować to ponownie?"
```

Nieprecyzyjne sformułowania typu `kiedyś` są odrzucane. Obsługiwane są m.in. `za 15 minut`, `jutro`, `za tydzień`, `za dwa tygodnie`, `za miesiąc`.

Kliknięcie `Zaplanuj ponownie` nie tworzy wydarzenia automatycznie. System ustawia jedynie nowy draft CREATE z zachowanym tytułem aktywności i prosi użytkownika o brakujące dane. Dopiero standardowe podsumowanie i jawne potwierdzenie może wykonać zapis do Google Calendar.

## Baza danych

Domyślna lokalna konfiguracja:

```text
Server=DESKTOP-SN6B47K
Database=ai_organizer
Trusted_Connection=Yes
Encrypt=Yes
TrustServerCertificate=Yes
```

Najważniejsze tabele:

- `dbo.users`,
- `dbo.learning_examples`,
- `dbo.conversation_feedback`,
- `dbo.chat_turn_metrics`,
- `dbo.event_reflections`,
- `dbo.motivation_reminders`.

Lokalny użytkownik developerski:

```text
external_id = local-user
users.id    = 00000000-0000-0000-0000-000000000001
```

Skrypty SQL:

- `sql/create_learning_tables.sql`,
- `sql/create_chat_turn_metrics.sql`,
- `sql/create_event_reflections.sql`,
- `sql/evaluation_summary.sql`,
- `sql/benchmark_run_summary.sql`,
- `sql/benchmark_repeat_summary.sql`.

## Metryki i ewaluacja

Każdy turn `/chat` może zostać zapisany do `dbo.chat_turn_metrics` z podziałem czasu na:

```text
latency_ms
llm_latency_ms
calendar_latency_ms
backend_latency_ms
```

Rejestrowane są także m.in. `operation`, `status`, liczba wywołań LLM/Calendar, informacja o konieczności doprecyzowania i obecności aktywnego draftu.

Dokumentacja ewaluacji:

- `docs/evaluation.md`,
- `docs/nlp_quality_v1.md`,
- `docs/nlp_quality_v2.md`,
- `docs/nlp_quality_v2_1.md`,
- `docs/nlp_quality_v3.md`,
- `docs/nlp_quality_v3_1.md`.

Zamrożony zbiór NLP znajduje się w `benchmarks/nlp_quality_v1.json`.

Benchmarki uruchamiane są m.in. przez:

```powershell
python scripts/benchmark_dialog.py
python scripts/benchmark_nlp.py --version v3.1 --policy deterministic
```

## Testy

Pełny zestaw testów:

```powershell
python -m unittest discover -s tests -v
```

Testy obejmują m.in.:

- wieloetapowy CREATE,
- anulowanie i potwierdzenia,
- parser dat i czasu trwania,
- delimited CREATE syntax,
- bezpieczny DELETE,
- deterministic dialog policy,
- metryki komponentowe,
- feedback learning loop,
- NLP refleksji,
- zakończone wydarzenia,
- parser czasu reminderów,
- handoff reminder → CREATE i zachowanie tytułu.

## Uruchomienie lokalne

Backend:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
streamlit run app/frontend/app.py
```

Ollama musi działać lokalnie i mieć dostępny model `mistral`.

Domyślny frontend korzysta z:

```text
http://127.0.0.1:8001
```

Adres można zmienić przez zmienną środowiskową `ORGANIZER_API_URL`.

## Końcowy przepływ systemu

```text
język naturalny
      ↓
interpretacja hybrydowa
      ↓
walidacja i polityka dialogowa
      ↓
Google Calendar
      ↓
zakończone wydarzenie
      ↓
refleksja NLP
      ↓
personalizacja / reminder
      ↓
propozycja ponownego zaplanowania
      ↓
bezpieczny CREATE
      ↓
Google Calendar
```

## Dokumentacja końcowa

- `docs/final_system_description.md` — pełny opis architektury, warstw, API i inwariantów bezpieczeństwa,
- `docs/final_validation.md` — procedura końcowego testu E2E i kryteria gotowości do merge,
- `tests/README.md` — zakres automatycznych testów regresyjnych,
- `docs/evaluation.md` — metodologia pomiaru dialogu i wydajności,
- `docs/nlp_quality_v*.md` — historia i interpretacja eksperymentów NLP.

Przed finalnym merge uruchom:

```powershell
python -m unittest discover -s tests -v
```

i przejdź scenariusz z `docs/final_validation.md`.
