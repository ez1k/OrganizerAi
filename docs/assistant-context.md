# OrganizerAI — project handoff context

Ten plik jest krótkim stanem projektu przeznaczonym do szybkiego wznowienia pracy w kolejnych sesjach.

## Repozytorium i branche

Repozytorium: `ez1k/OrganizerAi`

Aktualny branch roboczy:

```text
feature/learning-feedback-loop
```

Branch bazowy dla tej funkcjonalności:

```text
feature/sql-server-learning-store
```

Domyślny branch repozytorium: `master`.

## Cel aplikacji

OrganizerAI jest konwersacyjnym asystentem kalendarza w języku polskim. Użytkownik rozmawia z aplikacją naturalnie, backend interpretuje intencję i wykonuje operacje w Google Calendar.

Docelowo system ma uczyć się na zweryfikowanych przykładach użytkownika, ale aktualny mechanizm nie wykonuje fine-tuningu wag modelu. Używa retrieval + few-shot learning.

## Stack

- FastAPI — backend
- Streamlit — frontend
- Google Calendar API — kalendarz
- Ollama + `mistral` — lokalny LLM
- SQL Server — trwałe przykłady i feedback
- SQLAlchemy + pyodbc — dostęp do SQL Server

Strefa kalendarza:

```text
Europe/Warsaw
```

Techniczne timestampy w SQL Server są zapisywane w UTC.

## Uruchomienie

Backend:

```bash
uvicorn app.main:app --reload
```

Frontend:

```bash
streamlit run app/frontend/app.py
```

Ollama:

```text
http://localhost:11434/api/chat
model = mistral
```

## SQL Server

Lokalny serwer:

```text
DESKTOP-SN6B47K
```

Baza aplikacji:

```text
ai_organizer
```

Tabele:

```text
dbo.users
dbo.learning_examples
dbo.conversation_feedback
```

Lokalny użytkownik developerski:

```text
external_id = local-user
users.id    = 00000000-0000-0000-0000-000000000001
```

Domyślne połączenie aplikacji:

```text
Server=DESKTOP-SN6B47K
Database=ai_organizer
Trusted_Connection=Yes
Encrypt=Yes
TrustServerCertificate=Yes
```

ODBC Driver 18 wymaga wartości ODBC takich jak `Encrypt=Yes`, a nie `Encrypt=True`. `database.py` normalizuje także connection string pochodzący ze zmiennej `SQL_SERVER_CONNECTION`.

## Główne pliki

```text
app/frontend/app.py              Streamlit UI i feedback 👍/👎
app/routes/chat.py               główna logika konwersacji i Google Calendar
app/routes/feedback.py           API feedbacku i korekt
app/services/llm_service.py      Ollama / Mistral + few-shot context
app/services/database.py         SQL Server, users, learning examples, feedback
app/services/google_calendar.py  Google Calendar API
app/services/date_parser.py      parser polskich dat i godzin
app/schemas.py                   modele requestów Pydantic
sql/create_learning_tables.sql   schemat SQL Server
README.md                        dokumentacja projektu
```

## Operacje LLM

Model zwraca jedną z operacji:

```text
create
search
delete
external_search
chat
```

Dla `create` używane są m.in.:

```text
title
date_hint
time_hint
duration_minutes
description
```

Dla `search` / `delete`:

```text
title
date_hint
time_hint
range_type
range_days
```

Backend, a nie model, wykonuje operacje Google Calendar.

## Google Calendar — ważne zachowania

- CREATE wymaga potwierdzenia.
- DELETE wymaga potwierdzenia.
- SEARCH nie wymaga potwierdzenia.
- Wyniki wyszukiwania są numerowane.
- Delete obsługuje wybór numeru oraz usuwanie wszystkich wyników.
- Jest ochrona przed duplikatami przy tworzeniu wydarzeń.
- Wyszukiwanie bez tytułu nie przekazuje `q='None'` do Google API.
- Wyszukiwanie `najbliższe 2 tygodnie` oznacza `next_days = 14`.
- Liczby `2` i `14` w takich zakresach nie mogą zostać błędnie zinterpretowane jako godzina.

Format wyniku dla użytkownika:

```text
Znalazłem 2 wydarzenia:
1. spacer — poniedziałek, 10.08.2026, 18:00–19:00
2. spacer — piątek, 14.08.2026, 18:00–19:00
```

## Learning store

`learning_examples` zawiera dwa typy rekordów:

```text
corrected = 0  -> surowy / diagnostyczny / niezaufany
corrected = 1  -> zweryfikowany przez użytkownika
```

Tylko `corrected = 1` może być pobierane przez `find_learning_examples()` i przekazywane do Mistrala jako few-shot context.

Aktualny ranking podobieństwa jest prosty i opiera się na pokryciu tokenów wiadomości.

## Feedback loop

Frontend pokazuje przy ustrukturyzowanych interpretacjach:

```text
👍 Tak, poprawnie
👎 Nie, poprawię
```

Po 👍:

```text
conversation_feedback.model_result_json      = interpretacja
conversation_feedback.corrected_result_json  = interpretacja
learning_examples.corrected                  = 1
```

Po 👎:

1. błędna interpretacja trafia do `conversation_feedback.model_result_json`,
2. użytkownik wpisuje poprawkę jako następną wiadomość,
3. backend tworzy nową interpretację,
4. użytkownik musi ponownie kliknąć 👍,
5. dopiero wtedy poprawiona wersja trafia do `corrected_result_json` i `learning_examples.corrected = 1`.

Nie wolno automatycznie ufać poprawce bez potwierdzenia użytkownika.

## Deduplikacja

Aktualny kod w `app/services/database.py`:

- normalizuje JSON przed porównaniem,
- usuwa semantycznie puste wartości typu `null` i pusty string z danych porównawczych,
- nie dodaje kolejnego identycznego `corrected = 0`,
- nie dodaje kolejnego identycznego `corrected = 1`,
- jeśli identyczny przykład istnieje już jako `corrected = 1`, nie tworzy później kolejnego surowego `corrected = 0`,
- stare historyczne duplikaty `corrected = 0` pozostają w bazie jako audyt i nie są usuwane automatycznie.

Ostatnia zmiana deduplikacji na tym branchu:

```text
f8a081f  fix: avoid raw duplicates after verification
```

## Retrieval do Mistrala

`app/services/llm_service.py` pobiera maksymalnie 3 podobne zweryfikowane przykłady.

Model otrzymuje je jako wzorce semantyczne, ale prompt zabrania kopiowania konkretnych dat, godzin i tytułów, jeżeli nie występują w aktualnej wiadomości użytkownika.

Backend loguje liczbę pobranych zweryfikowanych przykładów. Przy zapytaniu przechodzącym przez LLM można szukać w logach komunikatu w rodzaju:

```text
LLM verified learning examples user_id=local-user count=1
```

Uwaga: część prostych zapytań jest obsługiwana deterministycznie przez `chat.py` i wtedy Ollama nie jest wywoływana, więc retrieval LLM również nie występuje.

## Ostatni potwierdzony test danych

Dla wiadomości:

```text
jakie mam wydarzenia w najbliższych 2 tygodniach?
```

zapisano zweryfikowany przykład:

```json
{"operation":"search","search":{"range_days":14,"range_type":"next_days"}}
```

oraz rekord `learning_examples.corrected = 1`.

W bazie są też wcześniejsze rekordy `corrected = 0`; retrieval je ignoruje.

## Polityka czasu

```text
SQL Server / created_at: UTC
Google Calendar / logika kalendarza: Europe/Warsaw
UI: docelowo konwersja UTC do strefy użytkownika
```

Przykład:

```text
2026-08-12 21:28:40 UTC
2026-08-12 23:28:40 Europe/Warsaw (CEST)
```

## Co testować po powrocie

1. Zrobić `git pull` na `feature/learning-feedback-loop`.
2. Zrestartować FastAPI i Streamlit.
3. Kilka razy wysłać identyczne zapytanie kalendarzowe.
4. Sprawdzić, czy liczba identycznych `corrected = 0` już nie rośnie.
5. Kliknąć 👍 drugi raz dla identycznej interpretacji i sprawdzić, czy nie powstaje drugi identyczny `corrected = 1`.
6. Przetestować 👎 -> poprawka -> 👍.
7. Przetestować bardziej swobodną frazę przechodzącą przez Ollamę i sprawdzić log `LLM verified learning examples ... count=N`.

Przykładowe zapytanie kontrolne:

```sql
USE [ai_organizer];

SELECT
    message,
    result_json,
    corrected,
    created_at
FROM dbo.learning_examples
ORDER BY created_at DESC;
```

Feedback:

```sql
SELECT
    message,
    model_result_json,
    corrected_result_json,
    created_at
FROM dbo.conversation_feedback
ORDER BY created_at DESC;
```

## Następne sensowne kroki

1. Testy jednostkowe dla feedback API i deduplikacji.
2. Lepszy ranking podobieństwa niż proste pokrycie tokenów.
3. Metryki jakości feedbacku: pozytywne/negatywne/korekty.
4. Rozdzielenie trwałego `user_id` od `session_id` po dodaniu logowania.
5. Embeddingi / wyszukiwanie wektorowe dopiero po zebraniu większej liczby zweryfikowanych przykładów.
6. Fine-tuning dopiero po zebraniu odpowiednio dużego i czystego zbioru danych.

## Zasada przy dalszych zmianach

Nie traktować surowej odpowiedzi modelu jako prawdy treningowej. Do promptu LLM powinny trafiać wyłącznie dane jawnie zweryfikowane przez użytkownika.
