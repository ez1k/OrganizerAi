# Finalna walidacja OrganizerAI

## Cel

Ten dokument opisuje końcową procedurę sprawdzenia aplikacji przed scaleniem wersji finalnej do `master`. Test łączy najważniejsze elementy systemu w jednej ścieżce: CREATE, SEARCH, refleksję NLP, reminder motywacyjny oraz ponowne wejście do bezpiecznego CREATE.

Automatyczne testy jednostkowe uruchamiane są osobno:

```powershell
python -m unittest discover -s tests -v
```

Walidacja E2E wymaga działającego backendu, Streamlita, Ollamy/Mistrala, SQL Server oraz skonfigurowanego Google Calendar.

## 1. Uruchomienie

Backend:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
streamlit run app/frontend/app.py
```

## 2. CREATE

Utwórz unikalne krótkie wydarzenie, np.:

```text
dodaj dzisiaj o 13:00 - spacer testowy E2E - 5 min
```

Oczekiwane zachowanie:

1. system rozpoznaje tytuł, datę, godzinę i czas trwania,
2. pokazuje finalne podsumowanie,
3. przed potwierdzeniem nie ma nowego wpisu w Google Calendar,
4. dopiero jednoznaczne `tak` wykonuje zapis,
5. odpowiedź zawiera potwierdzenie i dane utworzonego wydarzenia.

Inwariant bezpieczeństwa:

```text
interpretacja != zapis do Calendar
```

Mutacja może nastąpić dopiero po finalnym potwierdzeniu.

## 3. SEARCH

Wyszukaj utworzone wydarzenie, np.:

```text
znajdź spacer testowy E2E
```

Oczekiwany wynik: dokładnie utworzone wydarzenie z poprawną datą i godziną.

## 4. Refleksja po wydarzeniu

Po zakończeniu testowego wydarzenia użyj sekcji:

```text
⭐ Oceń ostatnie wydarzenia
```

Odśwież listę zakończonych wydarzeń i wybierz testowy wpis.

Przykładowa opinia:

```text
Było super, dobrze odpocząłem i zdecydowanie chciałbym to powtórzyć.
```

Można dodatkowo podać ocenę `5`.

Oczekiwany wynik NLP:

```text
sentiment = positive
rating = 5
worth_repeating = true
```

Kontrola SQL:

```sql
SELECT TOP 20
    id,
    calendar_event_id,
    event_title,
    rating,
    sentiment,
    feedback_text,
    worth_repeating,
    created_at
FROM dbo.event_reflections
ORDER BY id DESC;
```

Refleksja powinna być powiązana z konkretnym `calendar_event_id`. Ponowne pobranie zakończonych wydarzeń powinno oznaczyć ten wpis jako już oceniony.

## 5. Jawna zgoda na reminder

Po pozytywnej refleksji system może zapytać, czy użytkownik chce otrzymać przypomnienie o możliwości powtórzenia aktywności.

Kliknij:

```text
Tak, przypomnij
```

i podaj krótki termin testowy:

```text
za 2 minuty
```

Oczekiwany stan w bazie:

```sql
SELECT TOP 20
    id,
    reflection_id,
    remind_at,
    status,
    delivered_at,
    completed_at
FROM dbo.motivation_reminders
ORDER BY id DESC;
```

Nowy rekord powinien mieć:

```text
status = pending
```

Reminder nie może powstać bez jawnej zgody użytkownika.

## 6. Należny reminder

Po przekroczeniu `remind_at` wykonaj rerun/odświeżenie aplikacji.

Powinna pojawić się sekcja:

```text
🔔 Przypomnienia motywacyjne
```

z propozycją ponownego zaplanowania wcześniejszej aktywności.

Kliknięcie:

```text
📅 Zaplanuj ponownie
```

nie może samo utworzyć wydarzenia w Google Calendar.

Powinien powstać jedynie draft:

```json
{
  "operation": "create",
  "title": "spacer testowy E2E"
}
```

## 7. Handoff reminder → CREATE

Do utworzonego draftu podaj wyłącznie brakujące sloty:

```text
jutro o 18 na 30 min
```

Oczekiwany stan:

```json
{
  "operation": "create",
  "title": "spacer testowy E2E",
  "date_hint": "jutro",
  "time_hint": "18:00",
  "duration_minutes": 30
}
```

Kluczowa regresja: tytuł musi pozostać `spacer testowy E2E`. Fragment `jutro o 18 na` nie może zostać potraktowany jako nowy tytuł.

System powinien pokazać zwykłe podsumowanie CREATE i nadal nie modyfikować Calendar przed potwierdzeniem.

Dopiero kolejne jednoznaczne:

```text
tak
```

może utworzyć nowe wydarzenie.

## 8. Szybki test API handoffu

Regresję tytułu można sprawdzić bez czekania na reminder:

```powershell
$body = @{
    message = "jutro o 18 na 30 min"
    history = @()
    draft_event = @{
        operation = "create"
        title = "spacer testowy E2E"
    }
    user_id = "local-user"
    session_id = "manual-reminder-title-test"
} | ConvertTo-Json -Depth 6 -Compress

$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8001/chat" `
    -ContentType "application/json; charset=utf-8" `
    -Body $bodyBytes |
    ConvertTo-Json -Depth 10
```

Oczekiwany status:

```text
ready_for_confirmation
```

oraz zachowany tytuł.

## 9. Windows PowerShell i UTF-8

Windows PowerShell 5.1 może niepoprawnie wyświetlać UTF-8 zwracane przez FastAPI. Objawy to m.in.:

```text
â¢
â€“
dodaÄ
```

Jeżeli pola strukturalne JSON są poprawne, taki zapis nie oznacza błędu parsera backendu. Streamlit/Python normalnie obsługują UTF-8.

Dla requestów z polskimi znakami należy przekazywać body jako bajty UTF-8, jak w przykładzie powyżej.

## 10. Kryteria zakończenia

Wersję można uznać za gotową do merge, jeżeli:

- pełny `unittest discover` kończy się `OK`,
- CREATE nie mutuje Calendar przed potwierdzeniem,
- SEARCH znajduje zapisany event,
- reflection NLP zapisuje wynik do `event_reflections`,
- już oceniony event nie jest ponownie proponowany jako nieoceniony,
- reminder wymaga jawnej zgody,
- nieprecyzyjny termin typu `kiedyś` jest odrzucany,
- należny reminder nie tworzy eventu automatycznie,
- handoff reminder → CREATE zachowuje wcześniejszy tytuł,
- finalny zapis do Calendar następuje dopiero po kolejnym podsumowaniu i potwierdzeniu.

## 11. Finalny przepływ

```text
natural language
      ↓
CREATE + clarification
      ↓
explicit confirmation
      ↓
Google Calendar
      ↓
SEARCH
      ↓
completed event
      ↓
reflection NLP
      ↓
event_reflections
      ↓
explicit reminder consent
      ↓
motivation_reminders
      ↓
due reminder
      ↓
safe CREATE draft
      ↓
slot completion
      ↓
explicit confirmation
      ↓
Google Calendar
```
