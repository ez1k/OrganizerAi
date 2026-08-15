# NLP Quality v3 — semantic NLU + deterministic dialog policy

## Motywacja

Eksperymenty prompt-only na zamrożonym `benchmarks/nlp_quality_v1.json` pokazały rozdzielenie dwóch problemów:

- Mistral potrafi relatywnie dobrze wydobywać sloty semantyczne,
- decyzje o stanie dialogu (`needs_input`, `ready_for_confirmation`, `calendar_search`, itp.) pozostają niestabilne.

Wyniki pojedynczych runów:

| wariant | case pass | intent | status | slots | hallucination-free |
|---|---:|---:|---:|---:|---:|
| v1 | 54.17% | 95.65% | 75.00% | 77.27% | 75.00% |
| v2 | 45.83% | 73.91% | 66.67% | 79.55% | 87.50% |
| v2.1 | 45.83% | 86.96% | 58.33% | 95.45% | 87.50% |

v2.1 szczególnie dobrze pokazuje problem: `slot accuracy = 95.45%`, ale `status accuracy = 58.33%`.

## Architektura v3

v3 rozdziela NLU od policy:

```text
wiadomość użytkownika
        |
        v
Mistral / semantic NLU
operation + event/search slots
        |
        v
Deterministic dialog policy
status + high-confidence intent overrides
        |
        v
istniejące bezpieczne flow CREATE/SEARCH/DELETE
```

### Odpowiedzialność Mistrala

`app.services.llm_service.ask_llm_semantic()` zwraca surową interpretację:

- `operation`,
- `event` dla CREATE,
- `search` dla SEARCH/DELETE,
- krótki `reply`.

Prompt nie wymaga już od modelu podejmowania decyzji o `status`.

### Odpowiedzialność deterministic policy

`app.services.dialog_policy.apply_dialog_policy()`:

- stosuje high-confidence intent override dla jednoznacznych form typu `dodaj`, `usuń`, `co mam`, `pogoda`, `hej`,
- pozostawia niejednoznaczne wypowiedzi przy operacji rozpoznanej przez model,
- dla CREATE wylicza status na podstawie kompletności `title/date/time/duration`,
- usuwa nieprecyzyjne `time_hint` typu `wieczorem`,
- normalizuje fleksję dni tygodnia (`sobotę -> sobota`),
- SEARCH zawsze mapuje na `calendar_search`,
- DELETE bez kryteriów/kontekstu mapuje na `needs_input`,
- DELETE z kryteriami/kontekstem mapuje na `calendar_delete_confirmation`,
- external/chat/cancelled otrzymują deterministyczny status.

Runtime nadal korzysta z istniejącego `ask_llm()`, który teraz wykonuje:

```text
ask_llm_semantic -> apply_dialog_policy
```

Dzięki temu istniejące wywołania nie wymagają migracji.

## Bezpieczeństwo legacy DELETE

Stary core przy każdym `operation=delete` od razu przechodził do Calendar search. Dla `delete + needs_input` adapter runtime używa prywatnego route marker `__needs_input__`, zachowując `semantic_operation=delete`. Dzięki temu niedoprecyzowane DELETE nie powoduje nawet zbędnego odczytu Calendar przed dopytaniem użytkownika.

Benchmark v3 nie używa tego markera — ocenia bezpośrednio `apply_dialog_policy()`, więc semantyczna operacja pozostaje `delete`.

## Pomiar

Runner ma teraz dwa tryby:

### Raw semantic NLU

```powershell
python scripts/benchmark_nlp.py --version v3-raw --policy raw
```

Ten tryb służy do analizy samego Mistrala. Ponieważ model nie odpowiada już za status, `status accuracy` i `case pass` nie są głównymi metrykami tego trybu. Najważniejsze są:

- raw intent accuracy,
- slot accuracy,
- hallucination-free.

### NLU + deterministic policy

```powershell
python scripts/benchmark_nlp.py --version v3 --policy deterministic
```

To jest główny eksperyment systemowy v3. Runner waliduje wynik po policy, ale w JSON i podsumowaniu zachowuje także `raw_semantic_summary`:

- `raw intent accuracy`,
- `raw slot accuracy`,
- `raw hallucination-free`.

Dzięki temu można pokazać osobno wkład ML oraz poprawę zapewnianą przez warstwę deterministyczną.

## Warunki porównania

- dataset `nlp_quality_v1.json` pozostaje zamrożony,
- scorer pozostaje ten sam co dla v1/v2/v2.1,
- few-shoty nie kopiują wiadomości z datasetu,
- test nie wykonuje operacji Calendar,
- model pozostaje `mistral`,
- retrieval zweryfikowanych learning examples pozostaje aktywny.

Takie porównanie pozwala wykazać nie tylko końcową jakość systemu, ale również rozdzielić wkład modelu semantycznego od deterministic safety/policy.
