# NLP Quality v3.1 — deterministic grounding

## Punkt wyjścia

Wariant v3 rozdzielił interpretację semantyczną Mistrala od deterministycznej polityki dialogowej.
Na zamrożonym `benchmarks/nlp_quality_v1.json` pojedynczy run v3 (`policy=deterministic`) osiągnął:

- case pass rate: 79.17%,
- intent accuracy: 100.00%,
- status accuracy: 83.33%,
- slot accuracy: 93.18%,
- hallucination-free: 75.00%,
- raw semantic intent accuracy: 100.00%,
- raw semantic slot accuracy: 90.91%,
- raw semantic hallucination-free: 75.00%.

Pozostałe błędy ujawniły, że polityka poprawnie przejęła routing i statusy, ale nadal ufała części nieugruntowanych slotów zwracanych przez model.

## Hipoteza v3.1

Nowy slot bezpieczeństwa powinien wejść do stanu tylko wtedy, gdy ma podstawę w:

1. bieżącej wiadomości użytkownika, albo
2. wcześniej zwalidowanym aktywnym stanie CREATE/DELETE.

LLM nadal odpowiada za semantyczną interpretację i tytuły. Deterministyczny grounding dotyczy przede wszystkim wartości, które mogą zmienić wykonanie operacji bez wiedzy użytkownika: daty, dokładnej godziny, czasu trwania oraz kryteriów DELETE.

## Zmiany

`app/services/dialog_policy.py` w v3.1:

- odrzuca `duration_minutes`, jeśli bieżąca wiadomość ani aktywny stan nie zawierają podstawy dla czasu trwania,
- odrzuca dokładny `time_hint`, jeśli bieżąca wiadomość ani aktywny stan nie zawierają konkretnej godziny,
- potrafi deterministycznie odzyskać z wiadomości naturalne długości czasu, np. `półtorej godziny -> 90`,
- chroni konstrukcję `o 12 półtorej godziny` przed błędną interpretacją `12:30`,
- canonicalizuje odmiany dni tygodnia,
- dla potocznego DELETE odzyskuje bezpieczne kryteria z tekstu, np. `wywal mi trening z poniedziałku`,
- odrzuca ogólne, nieidentyfikujące cele DELETE takie jak `to wydarzenie`, jeśli nie ma kontekstu/matches,
- zachowuje istniejący, wcześniej zwalidowany stan przy korektach wieloturowych.

Prompt Mistrala, model, retrieval, frozen dataset oraz scoring benchmarku nie są zmieniane w ramach v3.1.

## Cel eksperymentu

Najważniejszą metryką v3.1 jest `hallucination-free`. Oczekujemy poprawy wynikającej wyłącznie z deterministic grounding, bez przypisywania tej poprawy modelowi.

Przy pięciu FAIL-ach v3 cztery dotyczyły bezpośrednio groundingu/policy. Jeden przypadek (`pouczenie się` vs oczekiwany semantyczny fragment tytułu) pozostaje kwestią reprezentacji semantycznej tytułu/scorera, a nie bezpieczeństwa zapisu.

## Pomiar

Po uruchomieniu testów regresyjnych:

```powershell
python -m unittest discover -s tests -v
python scripts/benchmark_nlp.py --version v3.1 --policy deterministic
```

Do porównania należy zachować równolegle:

- końcowe metryki systemowe po deterministic policy,
- sekcję `Raw semantic NLU`, która pokazuje rzeczywisty wkład modelu przed groundingiem.

Nie należy zmieniać `benchmarks/nlp_quality_v1.json` ani scorera przed tym pomiarem.
