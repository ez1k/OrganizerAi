# NLP Quality v2 — eksperyment prompt/few-shot

## Cel

NLP Quality v2 mierzy wpływ zmiany warstwy interpretacji modelowej na ten sam zamrożony dataset `benchmarks/nlp_quality_v1.json`.

Nie zmieniamy:

- modelu (`mistral`),
- datasetu 24 przypadków,
- temperatury modelu (`0.1`),
- sposobu retrieval zweryfikowanych przykładów SQL,
- reguł scoringu benchmarku.

Zmiana eksperymentalna obejmuje wyłącznie:

- rozszerzony `SYSTEM_PROMPT`,
- stałe few-shoty semantyczne w `app/services/llm_service.py`.

Stałe few-shoty są celowo parafrazami i nie mogą kopiować żadnej wiadomości z zamrożonego datasetu. Jest to kontrolowane testem automatycznym.

## Baseline v1

Pierwszy pomiar przed zmianą promptu miał batch `1e6c2c1f` i dał:

- case pass rate: 54.17%,
- intent accuracy: 95.65%,
- status accuracy: 75.00%,
- slot accuracy: 77.27%,
- hallucination-free: 75.00%,
- avg LLM latency: 3188 ms,
- median LLM latency: 3125 ms.

W baseline ujawniły się głównie następujące klasy błędów:

1. naturalne czasy trwania (`dwie godziny`, `półtorej godziny`, `90 minut`),
2. wymyślanie brakującej daty (`dziś`),
3. traktowanie `wieczorem` jako konkretnej godziny,
4. błędna decyzja `ready_for_confirmation` zamiast `needs_input`,
5. nierozpoznanie anulowania aktywnego flow,
6. pomylenie SEARCH z CREATE,
7. potoczny DELETE bez obiektu `search`,
8. błędna klasyfikacja external search i small-talku.

## Interwencja v2

Prompt v2 jawnie definiuje:

- mapowanie naturalnych czasów trwania,
- zakaz domyślnego `dzisiaj`, godziny i czasu trwania,
- `rano`, `po południu`, `wieczorem` jako nieprecyzyjne pory dnia,
- kontrakt statusów dla CREATE/SEARCH/DELETE/EXTERNAL/CHAT/CANCELLED,
- kanoniczne formy dni tygodnia,
- potoczne warianty CREATE i DELETE,
- rozdzielenie small-talku od SEARCH,
- zakaz generowania identyfikatorów wydarzeń przez model.

Few-shoty pokazują analogiczne, ale inne wypowiedzi niż test set, m.in. pełny CREATE z naturalnym duration, niepełny CREATE, nieprecyzyjną porę dnia, SEARCH z tytułem, potoczny DELETE, external search, chat i anulowanie.

## Protokół porównania

Najpierw uruchom testy:

```powershell
python -m unittest discover -s tests -v
```

Następnie jeden pomiar v2 na tym samym datasecie:

```powershell
python scripts/benchmark_nlp.py --version v2
```

Wynik zostanie zapisany jako:

```text
benchmark_results/nlp-v2-<batch_id>.json
```

Porównujemy bezpośrednio:

- case pass rate,
- intent accuracy,
- status accuracy,
- slot accuracy,
- hallucination-free,
- średnią i medianę latencji LLM.

Po pierwszym runie v2 można wykonać trzy powtórzenia:

```powershell
python scripts/benchmark_nlp.py --version v2 --runs 3
```

## Ważna uwaga o scoringu

Scorer pozostaje identyczny jak w baseline, aby zachować porównywalność. Znany przypadek fleksyjny `sobotę` vs `sobota` może więc nadal być raportowany jako błąd mimo równoważności semantycznej. Tę wadę pomiaru należy opisać osobno, a nie zmieniać scoring po zobaczeniu baseline.

## Kryterium sukcesu

Celem v2 nie jest 100%. Najważniejsze jest ograniczenie błędów bezpieczeństwa i dialogu. Kierunkowe cele:

- case pass rate > 75%,
- status accuracy > 90%,
- hallucination-free > 90%,
- brak pogorszenia intent accuracy.

Najbardziej istotnym wynikiem jest wzrost `hallucination-free`, ponieważ odpowiada bezpośrednio wymaganiu, aby system nie tworzył precyzyjnego wpisu na podstawie danych, których użytkownik nie podał.
