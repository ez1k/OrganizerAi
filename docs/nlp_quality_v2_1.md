# NLP Quality v2.1 — eksperyment minimalistycznego promptu

## Cel

Wariant v2.1 sprawdza, czy regresja jakości zaobserwowana w NLP v2 wynikała z przeciążenia Mistrala zbyt długim promptem oraz zbyt dużą liczbą stałych few-shotów.

Eksperyment używa dokładnie tego samego zamrożonego zbioru:

```text
benchmarks/nlp_quality_v1.json
```

oraz tego samego scorera `scripts/benchmark_nlp.py`. Dataset i kryteria oceny nie są zmieniane między v1, v2 i v2.1.

## Wyniki referencyjne

### NLP v1 — baseline

Batch: `1e6c2c1f`

- case pass rate: 54.17%
- intent accuracy: 95.65%
- status accuracy: 75.00%
- slot accuracy: 77.27%
- hallucination-free: 75.00%
- avg LLM latency: 3188 ms
- median LLM latency: 3125 ms

### NLP v2 — rozbudowany prompt + wiele few-shotów

Batch: `9bf0f565`

- case pass rate: 45.83%
- intent accuracy: 73.91%
- status accuracy: 66.67%
- slot accuracy: 79.55%
- hallucination-free: 87.50%
- avg LLM latency: 3128 ms
- median LLM latency: 2961 ms

V2 poprawiło kontrolę halucynacji o 12.50 pp, ale jednocześnie pogorszyło intent accuracy o 21.74 pp i case pass rate o 8.34 pp. Wariant został więc odrzucony jako konfiguracja docelowa.

## Hipoteza v2.1

Rozbudowany prompt v2 zawierał wiele szczegółowych reguł i dziewięć par few-shot. Zaobserwowane regresje, np. CREATE rozpoznawane jako SEARCH, DELETE rozpoznawane jako SEARCH oraz brak `operation` dla pytań zewnętrznych, sugerują nadmierne primowanie modelu przykładami.

V2.1 redukuje kontekst do:

1. krótkiej tabeli klasyfikacji intencji,
2. najważniejszych reguł slotów i bezpieczeństwa,
3. jednoznacznego kontraktu `operation -> status`,
4. pięciopunktowego self-checku przed zwróceniem JSON,
5. dokładnie trzech par few-shot dotyczących wyłącznie trudnych problemów slotowych:
   - naturalny czas trwania,
   - nieprecyzyjna pora dnia bez wymyślania godziny,
   - brak daty bez domyślnego `dzisiaj`.

Few-shoty są parafrazami i nie kopiują żadnego wejścia z zamrożonego datasetu. Test jednostkowy pilnuje braku identycznych wiadomości.

## Kryterium porównania

Uruchom:

```powershell
python scripts/benchmark_nlp.py --version v2.1
```

Wynik należy porównać bezpośrednio z v1 i v2.

Pożądany kierunek:

- intent accuracy wraca w okolice baseline v1 (preferowane >= 90%),
- status accuracy > 75%, docelowo >= 90%,
- hallucination-free utrzymuje większość poprawy v2 (preferowane >= 85%, docelowo >= 90%),
- case pass rate przewyższa v1 54.17%.

Najważniejszym wynikiem nie jest samo osiągnięcie arbitralnego progu, lecz ustalenie, czy redukcja promptu poprawia równowagę między klasyfikacją intencji a bezpieczeństwem slotów.

## Zasady metodologiczne

- Nie zmieniać `nlp_quality_v1.json` po zobaczeniu wyniku v2.1.
- Nie poluzowywać scorera między wariantami.
- Nie dodawać exact-match few-shotów z datasetu.
- Każdą kolejną zmianę promptu oznaczać osobną wersją eksperymentu.
- Dopiero po wyborze najlepszego wariantu wykonać kilka powtórzeń w celu oceny stabilności przy `temperature=0.1`.
