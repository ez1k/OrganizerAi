# Ewaluacja dialogu i wydajności

## Cel

Warstwa `chat_flow` mierzy każdy turn endpointu `/chat` i zapisuje metadane do `dbo.chat_turn_metrics`. Surowa treść wiadomości nie jest kopiowana do tabeli metryk.

Zapisywane pola:

- `session_id` — identyfikator sesji rozmowy; klient może go przesłać w `ChatRequest`, a backend ma deterministyczny fallback dla starszych klientów,
- `operation` — `create`, `search`, `delete`, `external_search` lub `chat`,
- `status` — końcowy status odpowiedzi backendu,
- `latency_ms` — czas obsługi turnu do momentu rozpoczęcia zapisu metryki,
- `clarification_required` — `1`, gdy odpowiedź ma status `needs_input`,
- `had_draft` — `1`, gdy użytkownik był już w wieloetapowym flow,
- `message_length` — liczba znaków wejścia, bez zapisywania jego treści,
- `created_at` — czas UTC po stronie SQL Server.

## Instalacja tabeli

W SSMS uruchom:

```sql
:r .\sql\create_chat_turn_metrics.sql
```

Jeśli `:r` nie jest dostępne w bieżącym trybie SSMS, otwórz plik `sql/create_chat_turn_metrics.sql` i wykonaj go bezpośrednio na bazie `ai_organizer`.

## Uruchomienie testów

```powershell
python -m unittest discover -s tests -v
```

## Raport ewaluacyjny

Po zebraniu danych uruchom `sql/evaluation_summary.sql`. Zapytania zwracają:

1. średnią i P95 latencji oraz odsetek turnów wymagających doprecyzowania per operacja,
2. liczbę turnów i doprecyzowań per sesja oraz informację, czy osiągnięto stan końcowy,
3. jakość pierwszej interpretacji na podstawie istniejącego feedbacku: wynik zaakceptowany bez korekty, wynik poprawiony po odrzuceniu oraz wpisy oczekujące na korektę.

W `conversation_feedback` pozytywna akceptacja zapisuje kanonicznie taki sam JSON w `model_result_json` i `corrected_result_json`. Korekta po odrzuceniu prowadzi do różnych wartości, dlatego można rozdzielić first-pass acceptance od correction rate bez zmiany istniejącego schematu feedbacku.

## Interpretacja do pracy

Najbardziej użyteczne wskaźniki do części eksperymentalnej:

- **first-pass acceptance rate** — udział interpretacji zaakceptowanych bez poprawki,
- **clarification rate** — udział turnów, w których system świadomie poprosił o brakujące dane,
- **turns per successful session** — liczba tur potrzebnych do zakończenia operacji,
- **average / P95 latency** — średni i wysokokwantilowy czas odpowiedzi,
- **error rate** — udział sesji zawierających status `error`.

Dla CREATE wyższy clarification rate nie musi oznaczać gorszej jakości: przy wymaganiu precyzyjnego wpisu doprecyzowanie jest pożądanym zachowaniem, jeśli zapobiega zapisaniu niepełnego wydarzenia.
