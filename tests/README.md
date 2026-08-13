# Regression tests

Uruchom z katalogu głównego projektu, przy aktywnym `.venv`:

```powershell
python -m unittest discover -s tests -v
```

Testy w `test_create_flow.py` nie wykonują prawdziwych zapisów do Google Calendar. Wywołania LLM, zapisu do Calendar i zapisu przykładów są mockowane tam, gdzie operacja mogłaby mieć efekt uboczny.

Aktualny zakres:

- brak `duration_minutes` blokuje zapis nawet wtedy, gdy LLM próbuje podstawić domyślne `60 min`,
- kontynuacje `90 min, trening nóg` oraz `trening nóg, 90 min`,
- korekta godziny przy zachowaniu pozostałych pól draftu,
- brak wywołania Calendar API przy niekompletnym evencie,
- pojedynczy zapis po kompletnym potwierdzeniu,
- dodatkowe potwierdzenie przy duplikacie,
- pytanie `na pewno dodałeś?` nie może udawać wykonanego zapisu,
- naturalne potwierdzenia `ok dodaj`, `dawaj`, `no dodaj`, `dodawaj`.
