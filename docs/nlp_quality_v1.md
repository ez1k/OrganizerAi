# NLP Quality Benchmark v1

## Cel

`benchmarks/nlp_quality_v1.json` jest zamrożonym zbiorem do oceny jakości warstwy NLP/ML OrganizerAI. Nie mierzy działania Google Calendar ani deterministycznych fast-pathów backendu.

Runner `scripts/benchmark_nlp.py` wywołuje bezpośrednio `app.services.llm_service.ask_llm`, dlatego wynik obejmuje:

- interpretację przez lokalny model Mistral,
- aktualny system prompt,
- retrieval zweryfikowanych przykładów `learning_examples` dla wskazanego użytkownika,
- strukturyzację odpowiedzi do JSON.

Nie są wykonywane operacje CREATE/DELETE na Google Calendar.

## Zbiór v1

Zestaw zawiera 24 nieidentyczne z benchmarkiem wydajności przypadki, w tym:

- kompletne CREATE zapisane naturalnym językiem,
- CREATE z brakującym dniem, godziną lub czasem trwania,
- nieprecyzyjne określenie `wieczorem`, dla którego model nie powinien wymyślać konkretnej godziny,
- korekty istniejącego draftu,
- anulowanie aktywnego CREATE,
- zmianę tematu z aktywnego CREATE na pytanie zewnętrzne,
- SEARCH dla dnia, godziny, zakresu i tytułu,
- DELETE jawny, potoczny i anaforyczny,
- DELETE bez wystarczającego celu, który powinien prowadzić do doprecyzowania,
- pytania zewnętrzne i zwykły chat.

Po pierwszym pomiarze datasetu v1 nie należy zmieniać pod wynik modelu. Zmiany jakości modelu należy porównywać na tym samym zbiorze. Nowe przypadki powinny trafić do kolejnej wersji datasetu.

## Metryki

Runner raportuje pięć głównych wskaźników:

1. **case pass rate** — udział przypadków, które przeszły wszystkie wymagane kontrole,
2. **intent accuracy** — poprawność `operation`, np. `create`, `search`, `delete`, `external_search`,
3. **status accuracy** — poprawność stanu dialogu, np. `needs_input` albo `ready_for_confirmation`,
4. **slot accuracy** — poprawność jawnie oczekiwanych pól `title`, `date_hint`, `time_hint`, `duration_minutes` oraz kryteriów SEARCH/DELETE,
5. **hallucination-free rate** — poprawność zachowania slotów, których model nie powinien wymyślić; obejmuje m.in. brak domyślnej godziny i zakaz generowania `event_id` dla DELETE.

`case pass rate` jest metryką najbardziej rygorystyczną: pojedynczy błędny slot powoduje niezaliczenie całego przypadku. Dlatego w analizie należy pokazywać ją razem z dokładnością intencji i slotów.

## Elastyczność oceny tytułów

Tytuły nie są porównywane zawsze przez ścisłą równość. Dopuszczane są semantyczne fragmenty po normalizacji wielkości liter i polskich znaków, np. `siłownię` może spełnić oczekiwanie `silown`.

Dzień, godzina i czas trwania są oceniane rygorystyczniej. `18`, `o 18` oraz `18:00` są traktowane jako ta sama godzina.

## Pierwszy pomiar

Przy działającej Ollamie i lokalnej bazie:

```powershell
python scripts/benchmark_nlp.py
```

Wynik jest zapisywany do ignorowanego przez Git pliku:

```text
benchmark_results/nlp-v1-<batch_id>.json
```

Plik zawiera również surową strukturalną odpowiedź modelu dla każdego przypadku, co pozwala analizować konkretne błędy po zakończeniu pomiaru.

Cel testu nie polega na uzyskaniu 100%. Domyślnie skrypt kończy się kodem `0` nawet przy błędach jakościowych. Opcjonalny quality gate można ustawić przez:

```powershell
python scripts/benchmark_nlp.py --min-pass-rate 80
```

## Powtarzalność

Po pierwszym pojedynczym runie warto wykonać kilka powtórzeń:

```powershell
python scripts/benchmark_nlp.py --runs 3
```

Przy `temperature=0.1` model może wykazywać niewielką zmienność. Wielokrotny run pozwala sprawdzić, czy błędy są systematyczne, czy przypadkowe.

## Interpretacja do pracy

Benchmark wydajności v1 i NLP Quality v1 mierzą różne rzeczy:

- **Benchmark wydajności v1** — wydajność całego systemu i koszt ścieżek deterministic / Calendar / LLM,
- **NLP Quality v1** — poprawność samej interpretacji języka przez Mistrala z aktualną warstwą retrieval.

Takie rozdzielenie pozwala niezależnie odpowiedzieć na dwa pytania badawcze: czy system działa szybko oraz czy model poprawnie interpretuje naturalne wypowiedzi użytkownika.
