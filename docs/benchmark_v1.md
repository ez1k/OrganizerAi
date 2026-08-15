# Benchmark dialogu v1

## Zamrożony zestaw

Benchmark v1 używa pliku `benchmarks/dialog_scenarios_v1.json`.

Zestaw zawiera 13 scenariuszy i 17 turnów obejmujących:

- deterministyczny CREATE,
- CREATE z jednym brakującym slotem,
- naturalne anulowanie CREATE,
- kontrolowany fallback LLM,
- wieloetapowe uzupełnienie i korektę CREATE,
- pięć wariantów SEARCH,
- niedestrukcyjny DELETE bez dopasowania.

Pliku `dialog_scenarios_v1.json` nie należy zmieniać podczas zbierania wyników v1. Nowe scenariusze powinny trafiać do roboczego `dialog_scenarios.json` albo przyszłej wersji benchmarku.

## Próba techniczna

Przed pełną serią uruchom testy:

```powershell
python -m unittest discover -s tests -v
```

Następnie wykonaj mały batch kontrolny:

```powershell
python scripts/benchmark_repeat.py --runs 3
```

Runner domyślnie wykonuje jeden warm-up, który nie jest zaliczany do mierzonego batcha. Każdy mierzony run musi przejść wszystkie 13 scenariuszy.

Na końcu runner wypisuje m.in.:

```text
Measured result: 3/3 full runs passed
SQL run-id prefix: a1b2c%
JSON result: ...\benchmark_results\v1-a1b2c.json
```

## Pełna seria

Po poprawnym batchu kontrolnym uruchom:

```powershell
python scripts/benchmark_repeat.py --runs 30
```

Domyślne parametry eksperymentu:

- 30 mierzonych runów,
- 1 warm-up przed serią,
- 13 scenariuszy / 17 turnów na run,
- 0,2 s przerwy między runami,
- prawdziwy endpoint `/chat`, Ollama i Google Calendar,
- brak potwierdzeń mutujących CREATE/DELETE.

Wyniki klienta są zapisywane do `benchmark_results/v1-<batch>.json`. Katalog jest ignorowany przez Git, ponieważ są to dane eksperymentalne konkretnego środowiska, a nie kod źródłowy.

## Wynik JSON

JSON zawiera:

- identyfikator batcha i wszystkich runów,
- liczbę pełnych runów zakończonych sukcesem,
- `run_pass_rate_pct`,
- per scenariusz: `pass_rate_pct`, średnią, medianę, P95, odchylenie standardowe, minimum i maksimum client latency,
- surowe wyniki każdego runu i turnu.

Client latency obejmuje pełny round-trip HTTP widziany przez klienta.

## Wynik SQL

Po serii uruchom `sql/benchmark_repeat_summary.sql`.

Najbezpieczniej wpisać pięcioznakowy prefix wypisany przez runner:

```sql
DECLARE @batch_prefix NVARCHAR(5) = N'a1b2c';
```

Przy `NULL` raport próbuje automatycznie użyć najnowszego batcha.

Raport zwraca trzy grupy wyników:

1. per scenariusz — średnia, mediana, P95, odchylenie standardowe, min/max oraz średni udział LLM/Calendar/backend,
2. per execution path — `deterministic`, `calendar`, `llm`, `llm+calendar`,
3. per operacja — CREATE, SEARCH, DELETE wraz z clarification rate i liczbą wywołań komponentów.

Server latency nie obejmuje zapisu samej metryki do SQL, zgodnie z definicją instrumentacji aplikacji.

## Zasady interpretacji

Do części eksperymentalnej należy raportować osobno co najmniej:

- scenario pass rate,
- run pass rate,
- średnią, medianę, P95 i odchylenie standardowe latencji,
- LLM / Calendar / backend time share,
- clarification rate,
- porównanie deterministic vs LLM fallback.

Nie należy opierać wniosków wyłącznie na globalnej średniej wszystkich turnów, ponieważ pojedyncze wywołanie LLM ma inną charakterystykę czasową niż lokalny fast-path i Google Calendar API.
