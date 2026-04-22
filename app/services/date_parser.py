from datetime import datetime, timedelta

def build_datetime(date_hint: str):
    now = datetime.now()

    hint = date_hint.lower()

    if "jutro" in hint:
        base = now + timedelta(days=1)
    elif "pojutrze" in hint:
        base = now + timedelta(days=2)
    else:
        base = now

    if "rano" in hint:
        hour = 9
    elif "wieczorem" in hint:
        hour = 18
    else:
        hour = 18

    return base.replace(hour=hour, minute=0, second=0, microsecond=0)