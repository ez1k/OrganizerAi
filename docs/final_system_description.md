# Końcowy opis systemu OrganizerAI

## 1. Cel systemu

OrganizerAI jest lokalnym, konwersacyjnym asystentem organizacji czasu. Głównym celem systemu jest umożliwienie użytkownikowi zarządzania wydarzeniami i zadaniami za pomocą języka naturalnego, przy jednoczesnym zachowaniu kontroli nad operacjami modyfikującymi kalendarz.

System łączy metody przetwarzania języka naturalnego z deterministyczną logiką aplikacyjną. Model językowy jest wykorzystywany do interpretacji semantycznej swobodnych wypowiedzi, natomiast backend odpowiada za stan dialogu, walidację danych, politykę bezpieczeństwa oraz wykonanie operacji Google Calendar.

Takie rozdzielenie odpowiedzialności wynika z założenia, że model generatywny dobrze radzi sobie z rozumieniem niejednoznacznych form językowych, ale nie powinien samodzielnie decydować o wykonaniu operacji o skutkach zewnętrznych.

## 2. Technologie

Główne elementy stosu technologicznego:

- Python,
- FastAPI — backend i endpointy HTTP,
- Streamlit — interfejs użytkownika,
- Ollama + Mistral — lokalny model językowy,
- Google Calendar API — warstwa kalendarza,
- SQL Server — trwałe przechowywanie feedbacku, metryk, refleksji i reminderów,
- SQLAlchemy + pyodbc — dostęp do SQL Server,
- unittest — testy jednostkowe i regresyjne.

Logika kalendarza wykorzystuje strefę `Europe/Warsaw`. Techniczne znaczniki czasu w SQL Server są zapisywane w UTC.

## 3. Architektura wysokiego poziomu

```text
                         ┌──────────────────────┐
                         │      Streamlit       │
                         │  interfejs rozmowy   │
                         └──────────┬───────────┘
                                    │ HTTP / JSON
                                    ▼
                         ┌──────────────────────┐
                         │       FastAPI        │
                         │     chat_flow        │
                         └──────────┬───────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               │                    │                    │
               ▼                    ▼                    ▼
      ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
      │ deterministic   │  │ Ollama/Mistral  │  │ Google Calendar │
      │ dialog policy   │  │ semantic NLU    │  │      API        │
      └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
               │                    │                    │
               └────────────────────┼────────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │     SQL Server       │
                         │ feedback / metrics   │
                         │ reflection / reminder│
                         └──────────────────────┘
```

Najważniejszą cechą architektury jest hybrydowe przetwarzanie komunikatu. System nie traktuje wyniku LLM jako polecenia wykonawczego. Model proponuje strukturę semantyczną, a backend sprawdza, które informacje mają podstawę w wypowiedzi użytkownika lub w już zwalidowanym stanie dialogu.

## 4. Warstwa konwersacyjna

Publiczny endpoint `/chat` jest obsługiwany przez `app/routes/chat_flow.py`. Warstwa ta pełni funkcję kontrolera dialogu i odpowiada m.in. za:

- wykrywanie bezpiecznych fast-pathów,
- normalizację potwierdzeń,
- anulowanie aktywnego flow,
- konserwatywną obsługę DELETE,
- ochronę istniejącego draftu,
- zapis metryk turnu,
- delegowanie bardziej niejednoznacznych przypadków do głównego routera i LLM.

Główna logika semantyczna i kalendarzowa znajduje się w `app/routes/chat.py`. Stan operacji jest przekazywany między turnami jako `draft_event`.

Przykładowy stan CREATE:

```json
{
  "operation": "create",
  "title": "trening siłowy",
  "date_hint": "jutro",
  "time_hint": "18:00",
  "duration_minutes": 60
}
```

Dzięki temu użytkownik może przekazywać dane etapami zamiast formułować pełne polecenie w jednej wiadomości.

## 5. Hybrydowe NLP

System wykorzystuje dwa podstawowe tryby interpretacji.

### 5.1. Deterministyczny fast-path

Jeżeli wiadomość jednoznacznie zawiera wymagane dane, backend może rozpoznać sloty bez wywołania modelu językowego. Dotyczy to szczególnie typowych konstrukcji CREATE, dat, godzin, czasu trwania oraz części kryteriów DELETE.

Korzyści:

- niższa latencja,
- pełna reprodukowalność,
- brak kosztu inferencji modelu,
- mniejsze ryzyko halucynacji wartości krytycznych.

### 5.2. LLM fallback

Wypowiedzi bardziej swobodne są przekazywane do lokalnego Mistrala. Model zwraca strukturę JSON opisującą intencję i rozpoznane pola.

Wynik nie jest jednak wykonywany bezpośrednio. Przechodzi przez deterministic grounding i sanityzację.

W praktyce oznacza to rozdzielenie:

```text
LLM = interpretacja semantyczna
backend = polityka dialogu i wykonanie
```

To rozdzielenie stanowi centralną decyzję projektową systemu.

## 6. Deterministic grounding

Warstwa bezpieczeństwa sprawdza, czy wartości mogące wpływać na operację kalendarza mają podstawę w:

1. bieżącej wiadomości użytkownika, albo
2. wcześniej zwalidowanym stanie aktywnego flow.

Szczególnej ochronie podlegają:

- data,
- dokładna godzina,
- czas trwania,
- tytuł podczas kontynuacji wieloturowego CREATE,
- kryteria identyfikujące wydarzenie w DELETE.

Przykład reguły zachowania tytułu:

```text
aktywny draft:
  title = "spacer testowy E2E"

użytkownik:
  "jutro o 18 na 30 min"
```

Nowa wiadomość uzupełnia `date_hint`, `time_hint` i `duration_minutes`, ale nie może heurystycznie zastąpić wcześniej zwalidowanego tytułu tekstem `jutro o 18 na`.

Jeżeli użytkownik chce rozpocząć jawne nowe polecenie CREATE z innym tytułem, może to zrobić explicite.

## 7. Wieloetapowy CREATE

CREATE ma cztery wymagane dane:

- tytuł,
- dzień,
- godzina rozpoczęcia,
- czas trwania.

Niekompletny stan prowadzi do `needs_input`. Backend zadaje pytanie tylko o brakujące informacje.

Po zebraniu kompletu danych generowane jest podsumowanie:

```text
Podsumowanie wydarzenia:
• spacer
• wtorek, 25.08.2026
• 18:00–18:30 (30 min)

Czy mam dodać to wydarzenie do Google Calendar?
```

Dopiero jednoznaczne potwierdzenie użytkownika może wykonać operację `events.insert` w Google Calendar.

W ten sposób system realizuje wymaganie, aby nie tworzyć wydarzenia, które nie zostało precyzyjnie ustalone.

## 8. SEARCH i DELETE

SEARCH działa jako operacja odczytowa i może wyszukiwać wydarzenia na podstawie tytułu, dnia, godziny oraz zakresów czasu.

DELETE jest bardziej restrykcyjny. System:

- nie usuwa niczego podczas pierwszej interpretacji,
- przy wielu wynikach wymaga wskazania wydarzenia,
- rozdziela wybór `usuń wszystkie` od późniejszego potwierdzenia,
- wymaga jednoznacznej odpowiedzi przed mutacją,
- blokuje zbyt ogólne lub niejednoznaczne kryteria.

Bezpieczne rozdzielenie interpretacji od wykonania jest szczególnie istotne w operacjach destrukcyjnych.

## 9. Feedback i mechanizm uczenia

OrganizerAI posiada mechanizm zbierania feedbacku do interpretacji kalendarzowych.

Po odpowiedzi systemu użytkownik może oznaczyć interpretację jako poprawną lub błędną.

```text
interpretacja
    ↓
👍 poprawna
    ↓
verified learning example
```

lub:

```text
interpretacja
    ↓
👎 błędna
    ↓
korekta użytkownika
    ↓
ponowne jawne potwierdzenie
    ↓
verified learning example
```

Do promptu LLM trafiają wyłącznie zweryfikowane rekordy `corrected = 1`.

Mechanizm nie jest fine-tuningiem modelu. Jest to retrieval + few-shot learning na przykładach zatwierdzonych przez użytkownika.

Dzięki temu dane treningowe nie są zasilane automatycznie błędnymi interpretacjami modelu.

## 10. Refleksja po zakończonym wydarzeniu

System rozszerza zwykły kalendarz o informację o doświadczeniu użytkownika po wykonanej aktywności.

Streamlit pobiera niedawno zakończone wydarzenia z Google Calendar i pozwala użytkownikowi wybrać jedno z nich oraz opisać je własnymi słowami.

Przykład:

```text
"Było super, dobrze odpocząłem i zdecydowanie chciałbym to powtórzyć."
```

`reflection_nlp_service.py` przesyła opinię do Mistrala i oczekuje ustrukturyzowanej odpowiedzi:

- `sentiment` — positive / neutral / negative / mixed,
- `rating` — 1–5 albo `null`,
- `worth_repeating` — true / false / null,
- `confidence`,
- krótkie `summary`.

Deterministyczna sanityzacja weryfikuje wynik. Jeżeli użytkownik poda ocenę jawnie, np. `5/5`, ta wartość ma pierwszeństwo przed estymacją modelu.

Refleksja jest zapisywana do `dbo.event_reflections` razem z identyfikatorem konkretnego wydarzenia Google Calendar.

## 11. Motywacja i reminders

Po pozytywnej refleksji system może zaproponować motywacyjne przypomnienie.

Najważniejszą zasadą jest konieczność jawnej zgody użytkownika.

```text
positive / worth_repeating
        ↓
"Czy chcesz, żebym przypomniał Ci o tej aktywności?"
        ↓
TAK
        ↓
"Za jaki czas?"
```

Termin jest interpretowany przez deterministyczny `motivation_time_service.py`, a nie bezpośrednio przez LLM.

Obsługiwane są wysokiej pewności wyrażenia względne, np.:

- `za 15 minut`,
- `za godzinę`,
- `jutro`,
- `za tydzień`,
- `za dwa tygodnie`,
- `za miesiąc`.

Sformułowania nieprecyzyjne, takie jak `kiedyś`, są odrzucane zamiast zgadywane.

Reminder trafia do `dbo.motivation_reminders` ze statusem `pending`.

## 12. Powrót reminderu do CREATE

Gdy reminder osiągnie swój termin, aplikacja pokazuje użytkownikowi propozycję ponownego zaplanowania dobrze ocenionej aktywności.

Kliknięcie `Zaplanuj ponownie` nie tworzy wpisu w Google Calendar.

Powstaje jedynie draft:

```json
{
  "operation": "create",
  "title": "spacer"
}
```

Następnie użytkownik podaje brakujące sloty, np.:

```text
"jutro o 18 na 30 min"
```

System zachowuje tytuł wynikający z refleksji i uzupełnia wyłącznie termin oraz czas trwania. Po wygenerowaniu pełnego podsumowania nadal wymagane jest standardowe potwierdzenie CREATE.

Otrzymujemy więc zamknięty przepływ:

```text
Calendar
   ↓
completed event
   ↓
reflection NLP
   ↓
user preference
   ↓
explicit reminder consent
   ↓
motivation reminder
   ↓
suggestion
   ↓
safe CREATE draft
   ↓
clarification
   ↓
confirmation
   ↓
Calendar
```

## 13. Warstwa danych

Najważniejsze tabele SQL Server:

### `dbo.users`
Mapowanie identyfikatora aplikacji na stabilny identyfikator bazodanowy.

### `dbo.learning_examples`
Przykłady interpretacji używane przez retrieval/few-shot.

### `dbo.conversation_feedback`
Surowy feedback i korekty interpretacji.

### `dbo.chat_turn_metrics`
Metryki turnów rozmowy oraz rozbicie latencji na komponenty.

### `dbo.event_reflections`
Oceny zakończonych wydarzeń, powiązane z identyfikatorem Google Calendar.

### `dbo.motivation_reminders`
Przypomnienia utworzone po jawnej zgodzie użytkownika.

## 14. Metryki działania

System instrumentuje endpoint `/chat` i mierzy:

- całkowitą latencję,
- czas LLM,
- czas Google Calendar,
- czas pozostałej logiki backendu,
- liczbę wywołań LLM,
- liczbę wywołań Calendar,
- wymaganie doprecyzowania,
- obecność aktywnego draftu,
- status końcowy turnu.

Pozwala to eksperymentalnie rozdzielić koszt semantycznej inferencji modelu od kosztu komunikacji z zewnętrznym API i deterministycznej logiki lokalnej.

Dokładna metodologia znajduje się w `docs/evaluation.md`.

## 15. Ewaluacja NLP

Projekt zawiera zamrożony zbiór benchmarkowy oraz kolejne warianty eksperymentu NLP: v1, v2, v2.1, v3 i v3.1.

Najważniejszy wniosek z eksperymentów jest jakościowy: samo rozszerzanie promptu nie dawało stabilnej poprawy. Największą poprawę uzyskano po rozdzieleniu interpretacji semantycznej modelu od deterministycznej polityki dialogu i groundingu danych.

W pracy można ten wynik opisać następująco:

> Rozbudowanie samego prompt engineeringu nie zapewniło stabilnej poprawy jakości. Największy wzrost skuteczności uzyskano po rozdzieleniu interpretacji semantycznej realizowanej przez model językowy od deterministycznej polityki zarządzania dialogiem i warstwy walidacji danych.

Szczegółowe warianty opisują pliki `docs/nlp_quality_*.md`.

## 16. Testowanie

Testy jednostkowe i regresyjne obejmują m.in.:

- parsowanie CREATE,
- obsługę wielu turnów,
- brakujące sloty,
- potwierdzenia i anulowanie,
- ochronę przed duplikatami,
- bezpieczny DELETE,
- deterministic grounding,
- pomiary komponentowe,
- reflection NLP,
- persistence refleksji,
- pobieranie zakończonych wydarzeń,
- parser terminu reminderu,
- reminder → CREATE handoff,
- zachowanie istniejącego tytułu podczas uzupełniania slotów.

Uruchomienie:

```powershell
python -m unittest discover -s tests -v
```

## 17. Ograniczenia aktualnej wersji

Aktualna implementacja jest rozwiązaniem lokalnym i demonstracyjnym. Najważniejsze ograniczenia:

- jeden lokalny użytkownik developerski zamiast pełnego systemu kont,
- lokalny Ollama wymaga działającego modelu Mistral,
- reminder jest sprawdzany przy uruchomieniu lub rerunie Streamlita, a nie wysyłany jako systemowe powiadomienie push,
- retrieval zweryfikowanych przykładów jest prostszy niż rozwiązania embeddingowe/wektorowe,
- nie jest wykonywany fine-tuning wag modelu,
- jakość zależy od językowego zakresu zamrożonego benchmarku i ręcznych scenariuszy integracyjnych.

Ograniczenia te nie naruszają głównego celu projektu, którym jest demonstracja bezpiecznego, konwersacyjnego asystenta czasu wykorzystującego NLP/ML.

## 18. Najważniejszy wniosek projektowy

OrganizerAI nie opiera bezpieczeństwa operacji kalendarzowych na poprawności odpowiedzi LLM.

Model jest ważnym komponentem NLP, ale decyzja o mutacji należy do aplikacji deterministycznej i użytkownika.

Finalny model odpowiedzialności można zapisać jako:

```text
Mistral
  → rozumie język i proponuje semantykę

Backend
  → waliduje, utrzymuje stan i egzekwuje reguły

Użytkownik
  → zatwierdza operację o skutkach zewnętrznych

Google Calendar
  → otrzymuje mutację dopiero po spełnieniu wszystkich warunków
```

Takie podejście pozwala połączyć elastyczność przetwarzania języka naturalnego z przewidywalnością i kontrolą wymaganą od aplikacji zarządzającej rzeczywistym kalendarzem.
