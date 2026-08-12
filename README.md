# OrganizerAI

OrganizerAI to konwersacyjny asystent kalendarza. Użytkownik rozmawia z aplikacją po polsku, a backend interpretuje intencję, wykonuje operacje w Google Calendar i docelowo wykorzystuje SQL Server do zapisywania przykładów uczenia i feedbacku.

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
- formatowanie wyników wyszukiwania do tekstu przeznaczonego dla użytkownika.

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

### `app/services/database.py`

Warstwa SQLAlchemy/pyodbc do SQL Server. Odpowiada za zapis i wyszukiwanie przykładów uczenia.

Aktualnie wymaga jeszcze poprawienia mapowania identyfikatora użytkownika: frontend/backend posługują się zewnętrznym stringiem, np. `local-user`, podczas gdy `learning_examples.user_id` w schemacie SQL jest kluczem `UNIQUEIDENTIFIER` do tabeli `users`.

### `sql/create_learning_tables.sql`

Docelowy schemat SQL Server dla:

- `users`,
- `learning_examples`,
- `conversation_feedback`.

### `app/services/event_service.py`

Starszy, tymczasowy magazyn wydarzeń w pamięci procesu (`events_db = []`). Nie jest trwałym magazynem danych i nie powinien być traktowany jako docelowa baza.

## Identyfikacja użytkownika w Streamlit

Aktualnie użytkownik **nie jest identyfikowany po adresie IP**.

`app/frontend/app.py` nie wysyła pola `user_id` do `/chat`. W konsekwencji Pydantic używa domyślnej wartości z `ChatRequest`:

```text
local-user
```

Oznacza to, że jeśli aplikację otworzy kilku użytkowników, backend widzi ich obecnie jako tego samego użytkownika z punktu widzenia mechanizmu uczenia/bazy danych.

`st.session_state` jest oddzielny dla sesji Streamlit, ale nie tworzy automatycznie trwałego identyfikatora użytkownika i nie jest identyfikatorem IP.

### Plan identyfikacji użytkownika

Etap 1, przed logowaniem:

1. Wygenerować UUID przy rozpoczęciu sesji Streamlit.
2. Zapisać go w `st.session_state.user_id`.
3. Wysyłać `user_id` w każdym requestcie do `/chat`.

Taki identyfikator rozdzieli równoczesne sesje, ale nie jest jeszcze trwałym kontem użytkownika.

Etap 2, docelowo:

- dodać logowanie,
- używać stabilnego ID konta jako `external_id`,
- mapować `external_id` do `users.id` w SQL Server.

Nie należy używać adresu IP jako głównego identyfikatora użytkownika: wiele osób może korzystać z jednego publicznego IP, a adres może się zmieniać lub pochodzić z proxy/VPN.

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
- `SQL_SERVER_ODBC_DRIVER`.

Schemat tabel znajduje się w `sql/create_learning_tables.sql`.

## Najbliższe prace techniczne

1. Dodać `user_id` do requestów Streamlit.
2. Dodać `get_or_create_user(external_id)` w warstwie SQL Server.
3. Zapisywać do `learning_examples` UUID z `users.id`, a nie bezpośrednio string `local-user`.
4. Usunąć podwójne zapisy przykładów między `llm_service.py` i `chat.py`.
5. Rozdzielić przykłady zweryfikowane przez użytkownika od surowych odpowiedzi modelu.
6. Stopniowo dodawać docstringi i testy jednostkowe do parserów dat, kryteriów wyszukiwania i formatowania wydarzeń.
