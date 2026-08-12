# OrganizerAI

OrganizerAI to konwersacyjny asystent kalendarza. Użytkownik rozmawia z aplikacją po polsku, a backend interpretuje intencję, wykonuje operacje w Google Calendar i wykorzystuje SQL Server do zapisywania przykładów uczenia.

## Architektura

Aktualny przepływ żądania:

```text
Streamlit
  app/frontend/app.py
        |
        | POST /chat
        v
FastAPI
  app/main.py
        |
        v
  app/routes/chat.py
        |
        +--> parser regułowy / stan rozmowy
        |
        +--> Ollama / Mistral
        |      app/services/llm_service.py
        |
        +--> Google Calendar API
        |      app/services/google_calendar.py
        |
        +--> SQL Server
               app/services/database.py
```

Backend działa w strefie czasowej `Europe/Warsaw`.

## Najważniejsze pliki

### `app/main.py`

Punkt wejścia FastAPI. Tworzy aplikację i rejestruje routery HTTP.

### `app/frontend/app.py`

Frontend Streamlit. Przechowuje historię rozmowy i aktualny `draft_event` w `st.session_state`, wysyła wiadomości do endpointu `/chat` i renderuje odpowiedzi asystenta.

### `app/routes/chat.py`

Główna logika konwersacyjna aplikacji. Odpowiada za:

- rozpoznawanie potwierdzeń i prostych intencji kalendarzowych,
- utrzymywanie stanu operacji create/search/delete,
- składanie kryteriów wyszukiwania,
- wykonywanie operacji Google Calendar,
- przekazywanie bardziej swobodnych wypowiedzi do LLM,
- formatowanie wyników wyszukiwania do tekstu przeznaczonego dla użytkownika,
- zapis znormalizowanych przykładów uczenia po stronie backendu.

Dane z Google Calendar pozostają wewnętrznie w ISO 8601, ale `_format_events()` zamienia je na czytelny polski format, np.:

```text
Znalazłem 2 wydarzenia:
1. spacer — poniedziałek, 10.08.2026, 18:00–19:00
2. spacer — piątek, 14.08.2026, 18:00–19:00
```

### `app/services/google_calendar.py`

Integracja z Google Calendar API:

- OAuth,
- tworzenie wydarzeń,
- wyszukiwanie wydarzeń,
- usuwanie wydarzeń,
- ochrona przed duplikatami,
- logi diagnostyczne zapytań Calendar API.

Plik `credentials.json` zawiera dane klienta OAuth. Token użytkownika jest przechowywany lokalnie w `token.pickle`.

### `app/services/date_parser.py`

Parser polskich dat i godzin oparty o `dateparser`. Zamienia wyrażenia typu `piątek o 18` na wartości `datetime` używane przez backend.

### `app/services/llm_service.py`

Warstwa komunikacji z lokalnym Ollama. Aktualnie używany model to `mistral` pod adresem:

```text
http://localhost:11434/api/chat
```

Model nie wykonuje operacji kalendarzowych bezpośrednio. Zwraca ustrukturyzowany JSON, a operacje wykonuje backend.

Warstwa LLM odczytuje przykłady z SQL Server jako few-shot context, ale nie zapisuje już automatycznie każdej swojej surowej interpretacji. Zapis jest wykonywany przez backend po normalizacji, co ogranicza dublowanie przykładów.

### `app/services/database.py`

Warstwa SQLAlchemy/pyodbc do SQL Server. Odpowiada za:

- konfigurację połączenia,
- mapowanie zewnętrznego `user_id` na `dbo.users.id`,
- automatyczne tworzenie użytkownika, jeśli jeszcze nie istnieje,
- zapis do `learning_examples`,
- odczyt przykładów dla tego samego użytkownika,
- przygotowanie przykładów jako kontekstu dla modelu.

### `sql/create_learning_tables.sql`

Schemat SQL Server dla:

- `users`,
- `learning_examples`,
- `conversation_feedback`.

Skrypt seeduje także lokalnego użytkownika developerskiego.

### `app/services/event_service.py`

Starszy, tymczasowy magazyn wydarzeń w pamięci procesu (`events_db = []`). Nie jest trwałym magazynem danych i nie powinien być traktowany jako docelowa baza.

## Identyfikacja użytkownika

Aktualnie aplikacja działa lokalnie z jednym stałym użytkownikiem:

```text
external_id = local-user
```

`app/frontend/app.py` nie wysyła jeszcze własnego `user_id`, dlatego Pydantic używa wartości domyślnej z `ChatRequest`:

```text
local-user
```

Po stronie SQL Server ten identyfikator jest mapowany na:

```text
00000000-0000-0000-0000-000000000001
```

Czyli aktualny przepływ wygląda tak:

```text
Streamlit
   ↓
user_id = local-user
   ↓
app/services/database.py
   ↓
dbo.users.external_id = local-user
   ↓
dbo.users.id = 00000000-0000-0000-0000-000000000001
   ↓
dbo.learning_examples.user_id
```

Jeżeli rekord `local-user` już istnieje w bazie z innym UUID, aplikacja respektuje istniejący rekord zamiast go nadpisywać.

Adres IP nie jest używany jako identyfikator użytkownika.

### Docelowa identyfikacja użytkownika

Po dodaniu logowania `local-user` zostanie zastąpiony stabilnym identyfikatorem konta, np. identyfikatorem Google. Mechanizm mapowania `external_id -> users.id` pozostanie bez zmian.

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

## Baza danych

Sterowniki Pythona dla SQL Server znajdują się w `requirements-db.txt`:

```text
SQLAlchemy>=2.0
pyodbc>=5.1
```

Połączenie jest konfigurowane przez zmienne środowiskowe:

- `SQL_SERVER_CONNECTION`,
- `SQL_SERVER_ODBC_DRIVER`,
- opcjonalnie `LOCAL_USER_EXTERNAL_ID`,
- opcjonalnie `LOCAL_USER_DB_ID`.

Domyślne wartości lokalnego użytkownika to:

```text
LOCAL_USER_EXTERNAL_ID=local-user
LOCAL_USER_DB_ID=00000000-0000-0000-0000-000000000001
```

Schemat tabel znajduje się w `sql/create_learning_tables.sql`.

### Pierwsze uruchomienie bazy

1. Utwórz bazę `OrganizerAI`, jeśli jeszcze nie istnieje.
2. Wykonaj `sql/create_learning_tables.sql` w SQL Server Management Studio.
3. Zainstaluj zależności z `requirements-db.txt`.
4. Uruchom backend i frontend.
5. Wykonaj operację wyszukiwania lub potwierdzonego tworzenia wydarzenia.
6. Sprawdź rekordy w `dbo.learning_examples`.

Przykładowa kontrola:

```sql
SELECT u.external_id, le.message, le.result_json, le.corrected, le.created_at
FROM dbo.learning_examples AS le
JOIN dbo.users AS u ON u.id = le.user_id
ORDER BY le.created_at DESC;
```

## Najbliższe prace techniczne

1. Dodać jawny mechanizm feedbacku i oznaczania przykładów jako `corrected = 1`.
2. Podłączyć `conversation_feedback` do procesu korekty odpowiedzi modelu.
3. Dodać trwałe logowanie użytkowników przed wdrożeniem wieloużytkownikowym.
4. Dodać testy jednostkowe dla warstwy SQL, parserów dat, kryteriów wyszukiwania i formatowania wydarzeń.
5. Stopniowo dodawać docstringi do pozostałych stabilnych modułów.
