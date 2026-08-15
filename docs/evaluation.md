# Ewaluacja dialogu i wydajności

## Cel

Warstwa `chat_flow` mierzy każdy turn endpointu `/chat` i zapisuje metadane do `dbo.chat_turn_metrics`. Surowa treść wiadomości nie jest kopiowana do tabeli metryk.

Zapisywane pola:

- `session_id` — identyfikator sesji rozmowy; klient może go przesłać w `ChatRequest`, a backend ma deterministyczny fallback dla starszych klientów,
- `operation` — `create`, `search`, `delete`, `external_search` lub `chat`,
- `status` — końcowy status odpowiedzi backendu,
- `latency_ms` — całkowity czas obsługi turnu do momentu rozpoczęcia zapisu metryki,
- `llm_latency_ms` — suma round-tripów HTTP do lokalnego modelu Ollama w danym turnie,
- `calendar_latency_ms` — suma faktycznych wywołań Google Calendar API `.execute()` w danym turnie,
- `backend_latency_ms` — pozostały czas turnu: parsing, logika deterministyczna, retrieval przykładów, budowanie odpowiedzi i pozostałe operacje aplikacji,
- `llm_calls` — liczba wywołań modelu w turnie,
- `calendar_calls` — liczba wykonanych żądań Google Calendar API w turnie,
- `timing_version` — wersja instrumentacji; rekordy z `timing_version >= 1` mają wiarygodny rozkład komponentowy,
- `clarification_required` — `1`, gdy odpowiedź ma status `needs_input`,
- `had_draft` — `1`, gdy użytkownik był już w wieloetapowym flow,
- `message_length` — liczba znaków wejścia, bez zapisywania jego treści,
- `created_at` — czas UTC po stronie SQL Server.

Zależność używana w analizie:

```text
latency_ms ≈ backend_latency_ms + llm_latency_ms + calendar_latency_ms
```

Różnica może wynosić pojedyncze milisekundy z powodu zaokrągleń; `backend_latency_ms` jest zabezpieczone przed wartością ujemną.

## Definicje komponentów

`llm_latency_ms` obejmuje żądanie `POST` do Ollamy i oczekiwanie na odpowiedź modelu. Retrieval zweryfikowanych przykładów z SQL wykonywany przed żądaniem modelu jest klasyfikowany jako czas backendu.

`calendar_latency_ms` obejmuje tylko faktyczne wywołania Google Calendar API przez `.execute()`. Dzięki temu sprawdzanie duplikatu może mieć jedno wywołanie Calendar, a faktyczne utworzenie wydarzenia kolejne. Budowa klienta API i lokalna obsługa poświadczeń pozostają w czasie backendu.

## Hybrydowe kierowanie CREATE

CREATE wykorzystuje dwa poziomy interpretacji:

1. **deterministyczny fast-path** — jeśli parser jednoznacznie wyodrębni wszystkie wymagane sloty (`title`, `date_hint`, `time_hint`, `duration_minutes`), backend buduje podsumowanie bez wywołania LLM,
2. **LLM fallback** — wypowiedzi niepełne lub niejednoznaczne są przekazywane do dotychczasowego routera i modelu, a wynik nadal podlega deterministycznej sanityzacji oraz walidacji backendu.

Fast-path nie wykonuje zapisu do Google Calendar. Niezależnie od sposobu interpretacji finalny CREATE nadal wymaga podsumowania i jawnego potwierdzenia użytkownika.

Takie rozwiązanie pozwala mierzyć kompromis między jakością NLP i wydajnością. Jednoznaczne polecenia nie ponoszą kosztu inferencji modelu, natomiast Mistral pozostaje odpowiedzialny za przypadki wymagające interpretacji języka naturalnego. W danych można to rozróżnić przez `llm_calls`: fast-path ma `llm_calls = 0`, a ścieżka modelowa `llm_calls > 0`.

## Instalacja / aktualizacja tabeli

W SSMS uruchom:

```sql
:r .\sql\create_chat_turn_metrics.sql
```

Jeśli `:r` nie jest dostępne w bieżącym trybie SSMS, otwórz plik `sql/create_chat_turn_metrics.sql` i wykonaj go bezpośrednio na bazie `ai_organizer`.

Skrypt jest idempotentny. Jeśli tabela już istnieje, doda brakujące kolumny komponentowe. Historyczne rekordy otrzymują `timing_version = 0`, natomiast nowe rekordy zapisywane przez aktualny backend mają `timing_version = 1`. Dzięki temu stare zera nie zaniżają statystyk komponentowych.

## Uruchomienie testów

```powershell
python -m unittest discover -s tests -v
```

Testy obejmują zarówno logikę wieloetapowego CREATE, granicę między deterministycznym fast-pathem i fallbackiem LLM, jak i arytmetykę podziału latencji oraz rejestrację round-tripów Ollama i Google Calendar.

## Raport ewaluacyjny

Po zebraniu danych uruchom `sql/evaluation_summary.sql`. Zapytania zwracają:

1. średnią i P95 całkowitej latencji oraz odsetek turnów wymagających doprecyzowania per operacja,
2. dla rekordów `timing_version >= 1`: średni czas backendu, średni czas LLM/Calendar gdy komponent był użyty, udział czasu poszczególnych komponentów i liczbę ich wywołań,
3. liczbę turnów i doprecyzowań per sesja, sposób zakończenia oraz sumę czasów komponentów w sesji,
4. jakość pierwszej interpretacji na podstawie istniejącego feedbacku: wynik zaakceptowany bez korekty, wynik poprawiony po odrzuceniu oraz wpisy oczekujące na korektę.

W `conversation_feedback` pozytywna akceptacja zapisuje kanonicznie taki sam JSON w `model_result_json` i `corrected_result_json`. Korekta po odrzuceniu prowadzi do różnych wartości, dlatego można rozdzielić first-pass acceptance od correction rate bez zmiany istniejącego schematu feedbacku.

## Interpretacja do pracy

Najbardziej użyteczne wskaźniki do części eksperymentalnej:

- **first-pass acceptance rate** — udział rozstrzygniętych interpretacji zaakceptowanych bez poprawki,
- **feedback resolution rate** — udział feedbacków, które zostały już rozstrzygnięte,
- **clarification rate** — udział turnów, w których system świadomie poprosił o brakujące dane,
- **turns per resolved session** — liczba tur potrzebnych do osiągnięcia wyniku końcowego, również gdy użytkownik świadomie anuluje operację,
- **average / P95 latency** — średni i wysokokwantilowy całkowity czas odpowiedzi,
- **LLM / Calendar / backend time share** — udział poszczególnych komponentów w czasie obsługi,
- **fast-path vs LLM latency** — różnica czasu obsługi jednoznacznych CREATE i CREATE wymagających modelu,
- **error rate** — udział sesji zawierających status `error`.

Dla CREATE wyższy clarification rate nie musi oznaczać gorszej jakości: przy wymaganiu precyzyjnego wpisu doprecyzowanie jest pożądanym zachowaniem, jeśli zapobiega zapisaniu niepełnego wydarzenia.
