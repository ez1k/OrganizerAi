# Regression tests

Uruchom z katalogu głównego projektu, przy aktywnym `.venv`:

```powershell
python -m unittest discover -s tests -v
```

Testy jednostkowe i regresyjne są projektowane tak, aby nie wykonywać niekontrolowanych mutacji w prawdziwym Google Calendar. Wywołania LLM, zapisu/usuwania Calendar oraz persistence są mockowane tam, gdzie operacja mogłaby mieć efekt uboczny.

## CREATE

Zakres obejmuje m.in.:

- brak `duration_minutes` blokuje zapis nawet wtedy, gdy model próbuje podstawić wartość domyślną,
- kontynuacje wieloturowe zachowują wcześniej zwalidowane sloty,
- korekta godziny nie usuwa tytułu, dnia ani czasu trwania,
- brak wywołania Calendar API przy niekompletnym evencie,
- pojedynczy zapis po kompletnym i jednoznacznym potwierdzeniu,
- dodatkowe potwierdzenie przy wykrytym duplikacie,
- pytanie `na pewno dodałeś?` nie może udawać wykonanego zapisu,
- potwierdzenia i anulowanie są rozróżniane od zwykłej rozmowy,
- parser obsługuje jednoznaczne formaty daty, godziny i czasu trwania,
- format `termin - tytuł - czas` nie może przypadkowo ustawić tytułu na przyimek lub fragment terminu.

## Reminder → CREATE

`test_reminder_create_handoff.py` zabezpiecza końcowy przepływ motywacyjny:

- draft z `title = "spacer testowy E2E"` + wiadomość `jutro o 18 na 30 min` zachowuje tytuł,
- slot-only continuation może uzupełnić tylko część brakujących pól bez wywołania LLM,
- jawne nowe polecenie CREATE może świadomie zastąpić poprzedni tytuł.

To jest regresja błędu, w którym tekst `jutro o 18 na` był wcześniej błędnie traktowany jako tytuł wydarzenia.

## SEARCH i DELETE

Testy obejmują:

- kryteria wyszukiwania i zakresy czasowe,
- wybór spośród wielu dopasowań,
- `usuń wszystkie` jako osobny krok,
- brak mutacji przed jednoznacznym potwierdzeniem,
- blokowanie niejednoznacznych potwierdzeń DELETE,
- anulowanie bez efektów ubocznych,
- brak prawdziwego usuwania podczas testów jednostkowych.

## NLP i dialog policy

Sprawdzane są m.in.:

- prompt i struktura JSON modelu,
- deterministic grounding dat, godzin i czasu trwania,
- zachowanie istniejącego stanu przy korektach,
- rozdzielenie semantycznego wyniku modelu od finalnej polityki dialogowej,
- frozen benchmark helpers.

## Feedback i learning loop

Testy weryfikują, że do przykładów używanych przez retrieval trafiają tylko dane zweryfikowane przez użytkownika, a błędna interpretacja wymaga korekty i ponownego potwierdzenia.

## Refleksje i motivation reminders

Zakres obejmuje:

- zapis refleksji powiązanej z konkretnym wydarzeniem Calendar,
- analizę naturalnej opinii przez Mistrala przy mockowanym HTTP,
- sanityzację `sentiment`, `rating`, `worth_repeating` i `confidence`,
- pierwszeństwo jawnej oceny użytkownika, np. `5/5`,
- brak persistence/reminder side effect w samym endpointcie `/reflections/analyze`,
- pobieranie zakończonych wydarzeń i oznaczanie tych już ocenionych,
- parser terminów typu `za 15 minut`, `za dwa tygodnie`, `za miesiąc`,
- odrzucenie nieprecyzyjnego `kiedyś`,
- zapis reminderu dopiero po interpretacji konkretnego terminu.

## Metryki

Testy komponentowe sprawdzają m.in.:

- `latency_ms`,
- `llm_latency_ms`,
- `calendar_latency_ms`,
- `backend_latency_ms`,
- liczbę wywołań LLM i Calendar,
- oznaczanie turnów wymagających doprecyzowania,
- zachowanie identyfikatora sesji.

## Test integracyjny ręczny

Pełna walidacja E2E wymaga działających usług lokalnych i prawdziwego Google Calendar, dlatego nie jest częścią automatycznego `unittest`. Procedura znajduje się w:

```text
docs/final_validation.md
```
