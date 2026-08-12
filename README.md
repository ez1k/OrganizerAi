# OrganizerAI

OrganizerAI to konwersacyjny asystent kalendarza. Użytkownik rozmawia z aplikacją po polsku, backend interpretuje intencję, wykonuje operacje w Google Calendar i wykorzystuje SQL Server do zapisywania przykładów oraz zweryfikowanego feedbacku.

## Architektura

```text
Streamlit
  app/frontend/app.py
        |
        | POST /chat
        v
FastAPI
  app/main.py
        |
        +--> app/routes/chat.py
        |      parser regułowy / stan rozmowy
        |
        +--> app/services/llm_service.py
        |      Ollama / Mistral
        |
        +--> app/services/google_calendar.py
        |      Google Calendar API
        |
        +--> app/routes/feedback.py
        |      feedback użytkownika
        |
        +--> app/services/database.py
               SQL Server / ai_organizer
```

Logika kalendarza działa w strefie `Europe/Warsaw`.

## Najważniejsze pliki

### `app/frontend/app.py`

Frontend Streamlit. Przechowuje historię rozmowy, `draft_event` oraz stan feedbacku w `st.session_state`. Wysyła wiadomości do `/chat` i pozwala oznaczyć ustrukturyzowaną interpretację jako poprawną lub błędną.

### `app/routes/chat.py`

Główna logika konwersacyjna aplikacji. Odpowiada za:

- rozpoznawanie potwierdzeń i prostych intencji kalendarzowych,
- utrzymywanie stanu create/search/delete,
- składanie kryteriów wyszukiwania,
- wykonywanie operacji Google Calendar,
- przekazywanie swobodnych wypowiedzi do LLM,
- formatowanie wyników wyszukiwania,
- zapis surowych, niezaufanych przykładów diagnostycznych z `corrected = 0`.

### `app/routes/feedback.py`

API feedbacku. Przyjmuje wynik widoczny w Streamlit, usuwa z niego dane runtime takie jak lista dopasowanych wydarzeń i zapisuje tylko strukturę istotną dla uczenia:

```json
{
  "operation": "search",
  "search": {
    "range_type": "next_days",
    "range_days": 14
  }
}
```

Obsługiwane są dwa przepływy:

- pozytywny feedback: interpretacja trafia do `conversation_feedback` i jest promowana do `learning_examples` z `corrected = 1`,
- negatywny feedback: zapisywany jest błędny wynik, użytkownik wpisuje poprawkę w czacie, a poprawiona interpretacja wymaga jeszcze potwierdzenia 👍 przed promocją.

### `app/services/llm_service.py`

Adapter do lokalnego Ollama (`mistral`, `http://localhost:11434/api/chat`). Model zwraca wyłącznie ustrukturyzowany JSON, a operacje wykonuje backend.

Przed zapytaniem do Ollamy pobierane są maksymalnie 3 podobne przykłady z SQL Server. Retrieval używa **wyłącznie rekordów `corrected = 1`**. Zweryfikowane przykłady są wzorcami semantycznymi; model nie powinien kopiować z nich dat, godzin ani tytułów, których nie ma w bieżącej wiadomości.

### `app/services/database.py`

Warstwa SQLAlchemy/pyodbc do SQL Server. Odpowiada za:

- połączenie z bazą `ai_organizer`,
- mapowanie `external_id` na `dbo.users.id`,
- zapis `learning_examples`,
- zapis i weryfikację `conversation_feedback`,
- deduplikację zweryfikowanych przykładów,
- retrieval zweryfikowanych przykładów dla tego samego użytkownika.

### `app/services/google_calendar.py`

Integracja z Google Calendar API: OAuth, tworzenie, wyszukiwanie, usuwanie wydarzeń oraz ochrona przed duplikatami.

### `app/services/date_parser.py`

Parser polskich dat i godzin oparty o `dateparser`.

### `sql/create_learning_tables.sql`

Schemat SQL Server dla:

- `users`,
- `learning_examples`,
- `conversation_feedback`.

Skrypt działa w bazie `ai_organizer` i seeduje lokalnego użytkownika developerskiego.

## Identyfikacja użytkownika

Aktualnie aplikacja lokalna korzysta z jednego użytkownika:

```text
external_id = local-user
users.id    = 00000000-0000-0000-0000-000000000001
```

Przepływ:

```text
Streamlit
   ↓
user_id = local-user
   ↓
app/services/database.py
   ↓
ai_organizer.dbo.users
   ↓
learning_examples / conversation_feedback
```

Adres IP nie jest używany jako identyfikator. Po dodaniu logowania `local-user` zostanie zastąpiony stabilnym ID konta, a mapowanie `external_id -> users.id` pozostanie bez zmian.

## Verified learning feedback loop

Aktualny mechanizm nie wykonuje fine-tuningu wag Mistrala. Jest to retrieval + few-shot learning na zweryfikowanych przykładach.

### Poprawna interpretacja

```text
wiadomość użytkownika
        ↓
backend interpretuje
        ↓
Streamlit pokazuje wynik
        ↓
👍 Tak, poprawnie
        ↓
conversation_feedback.corrected_result_json = wynik
        ↓
learning_examples.corrected = 1
        ↓
przyszłe podobne wiadomości mogą użyć przykładu jako few-shot
```

### Błędna interpretacja

```text
wiadomość użytkownika
        ↓
backend interpretuje błędnie
        ↓
👎 Nie, poprawię
        ↓
conversation_feedback zapisuje błędny model_result_json
        ↓
użytkownik wpisuje poprawkę w czacie
        ↓
backend tworzy nową interpretację
        ↓
👍 potwierdzenie poprawionej interpretacji
        ↓
corrected_result_json + learning_examples.corrected = 1
```

Jeżeli poprawiona interpretacja nadal jest błędna, użytkownik może ponownie wybrać 👎 i wpisać następną korektę. Do kontekstu LLM nie trafia nic, dopóki nie zostanie jawnie potwierdzone.

### Znaczenie `corrected`

```text
corrected = 0  → dane diagnostyczne / niezaufane, nie trafiają do promptu LLM
corrected = 1  → dane zweryfikowane przez użytkownika, mogą być użyte jako few-shot
```

Stare rekordy `corrected = 0` mogą pozostać w bazie; retrieval je ignoruje.

## Baza danych

Domyślne połączenie używa:

```text
Server=DESKTOP-SN6B47K
Database=ai_organizer
Trusted_Connection=Yes
Encrypt=Yes
TrustServerCertificate=Yes
```

Konfigurację można nadpisać przez:

- `SQL_SERVER_CONNECTION`,
- `SQL_SERVER_ODBC_DRIVER`,
- `LOCAL_USER_EXTERNAL_ID`,
- `LOCAL_USER_DB_ID`.

### Polityka czasu

Znaczniki techniczne `created_at` są zapisywane w UTC przez `SYSUTCDATETIME()`.

```text
SQL Server / created_at: UTC
Google Calendar / logika kalendarza: Europe/Warsaw
UI: konwersja UTC do strefy użytkownika przy wyświetlaniu
```

Przykład:

```text
SQL Server: 2026-08-12 21:28:40 UTC
Warszawa:   2026-08-12 23:28:40 CEST
```

Przykładowa kontrola danych:

```sql
USE [ai_organizer];

SELECT
    u.external_id,
    le.message,
    le.result_json,
    le.corrected,
    le.created_at
FROM dbo.learning_examples AS le
JOIN dbo.users AS u ON u.id = le.user_id
ORDER BY le.created_at DESC;
```

Zweryfikowane przykłady używane przez model:

```sql
SELECT
    message,
    result_json,
    created_at
FROM dbo.learning_examples
WHERE corrected = 1
ORDER BY created_at DESC;
```

Feedback i korekty:

```sql
SELECT
    message,
    model_result_json,
    corrected_result_json,
    created_at
FROM dbo.conversation_feedback
ORDER BY created_at DESC;
```

## Uruchomienie lokalne

Backend:

```bash
uvicorn app.main:app --reload
```

Frontend:

```bash
streamlit run app/frontend/app.py
```

Ollama musi działać lokalnie i mieć dostępny model `mistral`.

Zależności SQL Server znajdują się w `requirements-db.txt`.

## Najbliższe prace techniczne

1. Dodać testy jednostkowe dla feedback API, retrieval, parserów dat i formatowania wydarzeń.
2. Ulepszyć ranking podobieństwa przykładów (obecnie proste pokrycie tokenów).
3. Dodać metryki jakości: liczba pozytywnych/negatywnych feedbacków i skuteczność korekt.
4. Dodać trwałe logowanie użytkowników przed wdrożeniem wieloużytkownikowym.
5. Rozważyć embeddingi lub wyszukiwanie wektorowe dopiero po zebraniu większej liczby zweryfikowanych przykładów.
6. Fine-tuning modelu rozważać dopiero po zebraniu odpowiednio dużego, czystego zbioru danych.
