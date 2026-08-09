import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from google.auth.exceptions import RefreshError

from app.schemas import ChatRequest
from app.services.date_parser import build_event_time
from app.services.database import save_learning_example
from app.services.google_calendar import create_event, delete_event, search_events
from app.services.llm_service import ask_llm

router = APIRouter()
WARSAW = ZoneInfo("Europe/Warsaw")
CONFIRMATION_RE = re.compile(r"^(?:tak|potwierdzam|potwierdź|dodaj|zapisz|jasne|zgadza się|zgadza sie|ok|okej|okay|yes)[.!\s]*$", re.I)
THANKS_RE = re.compile(r"^(?:dzięki|dzieki|dziękuję|dziekuje|super|super dzięki|super dzieki|ok dzięki|ok dzieki)[.!\s]*$", re.I)
ALL_DELETE_RE = re.compile(r"^\s*(?:usuń|usun|skasuj|wywal)\s+(?:je|oba|obie|wszystkie|wszystko|wszystkie te)\s*[.!]?\s*$", re.I)


def _is_confirmation(message):
    normalized = " ".join(message.strip().lower().split())
    return bool(CONFIRMATION_RE.fullmatch(normalized) or (normalized.startswith("tak") and "potwierdz" in normalized))


def _is_thanks(message):
    return bool(THANKS_RE.fullmatch(" ".join(message.strip().lower().split())))


def _is_number_selection(message):
    match = re.fullmatch(r"\s*(\d+)\s*[.]?\s*", message)
    return int(match.group(1)) if match else None


def _is_delete_all(message): return bool(ALL_DELETE_RE.fullmatch(message))


def _is_calendar_search_intent(message):
    text = " ".join(str(message).strip().lower().split())
    patterns = (
        r"\bsprawdź\b", r"\bsprawdz\b", r"\bco\s+mam\b", r"\bjakie\s+mam\b",
        r"\bpokaż\b", r"\bpokaz\b", r"\bnajbliższe\s+wydarzenia\b",
        r"\bnajbliższych\s+(?:dwa|2)\s+tygodni", r"\bnajbliższe\s+(?:dwa|2)\s+tygodnie\b",
        r"\b(?:w|na)\s+tym\s+tygodniu\b", r"\b(?:na|w)\s+ten\s+tydzień\b",
        r"\bna\s+ten\s+tydzień\s+i\s+(?:następny|nastepny)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _merge_event(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint", "duration_minutes", "description"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""): merged[key] = value
    return merged or None


def _merge_search(draft, candidate):
    merged = dict(draft or {})
    for key in ("title", "date_hint", "time_hint", "range_type", "range_days"):
        value = candidate.get(key) if candidate else None
        if value not in (None, ""): merged[key] = value
    return merged


def _extract_search_criteria(message, criteria):
    text = " ".join(str(message).strip().lower().split())
    result = dict(criteria or {})
    multi_week = re.search(
        r"\bnajbliższe\s+(?:dwa|2)\s+tygodnie\b"
        r"|\bnajbliższych\s+(?:dwa|2|dwóch)\s+tygodni(?:e|ach)?\b"
        r"|\bw\s+najbliższych\s+(?:dwa|2|dwóch)\s+tygodni(?:e|ach)?\b"
        r"|\bnajbliższe\s+14\s+dni\b"
        r"|\bprzez\s+najbliższe\s+(?:dwa|2|dwóch)\s+tygodnie\b"
        r"|\b(?:na|w)\s+ten\s+tydzień\s+i\s+(?:następny|nastepny)\b",
        text,
    )
    if multi_week:
        result["range_type"], result["range_days"] = "next_days", 14
        result.pop("date_hint", None)
        result.pop("time_hint", None)
    elif re.search(r"\bnajbliższe\s+(?:wydarzenia|dni)\b|\bnajbliższych\s+wydarze(?:ń|nia)\b", text):
        result["range_type"], result["range_days"] = "next_days", 14
        result.pop("date_hint", None)
        result.pop("time_hint", None)
    elif re.search(r"\b(?:w|na)\s+tym\s+tygodniu\b", text):
        result["range_type"] = "this_week"
        result.pop("date_hint", None)
        result.pop("time_hint", None)

    explicit_date = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\b", text)
    if explicit_date:
        day, month = int(explicit_date.group(1)), int(explicit_date.group(2))
        year = int(explicit_date.group(3)) if explicit_date.group(3) else datetime.now(WARSAW).year
        result["date_hint"] = f"{day:02d}.{month:02d}.{year:04d}"
        result.pop("range_type", None); result.pop("range_days", None)

    day_patterns = [
        r"\b(?:w|z|na)\s+(poniedziałek|poniedzialek|wtorek|środę|srodę|srode|czwartek|piątek|piatek|sobotę|sobote|niedzielę|niedziele)\b",
        r"\b(poniedziałek|poniedzialek|wtorek|środa|sroda|czwartek|piątek|piatek|sobota|niedziela)\b",
        r"\b(dzisiaj|dziś|jutro|pojutrze)\b",
    ]
    for pattern in day_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            day = {"środę":"środa","srodę":"środa","srode":"środa","sobotę":"sobota","sobote":"sobota","niedzielę":"niedziela","niedziele":"niedziela"}.get(match.group(1), match.group(1))
            result["date_hint"] = day
            result.pop("range_type", None); result.pop("range_days", None)
            break

    time_match = re.search(r"\b(?:o\s*)?(\d{1,2})(?::(\d{2}))?\s*(?:godz(?:ina|iny|in)?|h)?\b", text)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59: result["time_hint"] = f"{hour:02d}:{minute:02d}"

    title_match = re.search(r"(?:usuń|usun|skasuj|wywal)\s+(.+?)(?=\s+(?:z|ze|w|we|o)\s+|$)", text, re.I)
    if title_match and not result.get("title"):
        title = title_match.group(1).strip(" .,!?-")
        if title and title not in {"je","oba","obie","wszystkie","wszystko"}: result["title"] = title
    return result


def _missing_event(event): return [k for k in ("title", "date_hint", "time_hint") if not event or not str(event.get(k, "")).strip()]


def _build_event(data):
    title, date_hint, time_hint = str(data.get("title","")).strip(), str(data.get("date_hint","")).strip(), str(data.get("time_hint","")).strip()
    duration = int(data.get("duration_minutes") or 60)
    if not title or not date_hint or not time_hint: raise ValueError("Brakuje nazwy, dnia lub godziny wydarzenia.")
    start, end = build_event_time(f"{date_hint} o {time_hint}", duration)
    return {"title": title, "description": str(data.get("description","")).strip(), "start": start.isoformat(), "end": end.isoformat()}


def _day_range(date_hint):
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", date_hint):
        day, month, year = map(int, date_hint.split(".")); start = datetime(year, month, day, tzinfo=WARSAW)
    else:
        start, _ = build_event_time(f"{date_hint} o 00:00", 1)
        if start.tzinfo is None: start = start.replace(tzinfo=WARSAW)
        else: start = start.astimezone(WARSAW)
    return start, start + timedelta(days=1)


def _normalize_time_hint(value):
    if not value: return None
    text = re.sub(r"^o\s*", "", str(value).strip().lower().replace(".", ":"))
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
    if not match: return text
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59: raise ValueError("Nieprawidłowa godzina wydarzenia.")
    return f"{hour:02d}:{minute:02d}"


def _normalize_search_criteria(criteria):
    normalized = dict(criteria or {})
    normalized["title"] = str(normalized.get("title", "")).strip() or None
    normalized["date_hint"] = str(normalized.get("date_hint", "")).strip() or None
    normalized["time_hint"] = _normalize_time_hint(normalized.get("time_hint"))
    return normalized


def _search_range(criteria):
    now = datetime.now(WARSAW)
    if criteria.get("range_type") == "next_days": return now, now + timedelta(days=int(criteria.get("range_days") or 14))
    if criteria.get("range_type") == "this_week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7)
    return None


def _search_calendar(criteria):
    criteria = _normalize_search_criteria(criteria)
    title, date_hint, time_hint = criteria["title"], criteria["date_hint"], criteria["time_hint"]
    range_window = _search_range(criteria)
    if range_window:
        start, end = range_window
        events = search_events(title=title, start=start, end=end, max_results=100)
        if time_hint:
            target = int(time_hint[:2]) * 60 + int(time_hint[3:])
            filtered = []
            for event in events:
                value = event.get("start", "")
                match = re.search(r"T(\d{2}):(\d{2})", value)
                if match and abs((int(match.group(1))*60 + int(match.group(2))) - target) <= 2: filtered.append(event)
            return filtered
        return events
    if not date_hint:
        start, end = _search_range({"range_type":"next_days","range_days":14})
        return search_events(title=title, start=start, end=end, max_results=100)
    day_start, day_end = _day_range(date_hint)
    if not time_hint: return search_events(title=title, start=day_start, end=day_end, max_results=100)
    target = day_start.replace(hour=int(time_hint[:2]), minute=int(time_hint[3:]), second=0, microsecond=0)
    return search_events(title=title, start=target-timedelta(minutes=2), end=target+timedelta(minutes=2), max_results=100)


def _format_events(events):
    if not events: return "Nie znalazłem żadnych wydarzeń."
    return "Znalazłem:\n" + "\n".join(f"{i}. {e['title']} — {e.get('start','?')} – {e.get('end','?')}" for i,e in enumerate(events,1))


class CalendarAuthRequired(Exception): pass


def _calendar_call(fn,*args,**kwargs):
    try: return fn(*args,**kwargs)
    except (FileNotFoundError,RefreshError) as exc: raise CalendarAuthRequired(str(exc)) from exc


def _last_matches(state):
    matches=state.get("matches") if isinstance(state,dict) else None
    return matches if isinstance(matches,list) else []


def _save_learning(request, result):
    try: save_learning_example(request.user_id, request.message, result, corrected=False)
    except Exception: pass


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    try:
        state = request.draft_event or {}
        selection = _is_number_selection(request.message)
        if selection is not None and _last_matches(state):
            matches = _last_matches(state)
            if 1 <= selection <= len(matches):
                selected = matches[selection-1]
                if state.get("operation") == "delete":
                    return {"status":"calendar_delete_confirmation","message":f"Wybrano „{selected['title']}”. Czy chcesz je usunąć?","event":{**state,"matches":[selected],"selected_event_id":selected.get("id")}}
                return {"status":"calendar_search","message":_format_events([selected]),"event":state}

        if state.get("operation") == "delete" and state.get("matches") and _is_delete_all(request.message):
            return {"status":"calendar_delete_confirmation","message":f"Znalazłem {len(state['matches'])} wydarzeń. Czy chcesz usunąć wszystkie?","event":{**state,"delete_all":True}}
        if state.get("operation") == "delete" and state.get("delete_all") and _is_confirmation(request.message):
            for event in state.get("matches",[]): _calendar_call(delete_event,event["id"])
            return {"status":"deleted","message":f"Usunięte: {len(state.get('matches',[]))} wydarzeń.","event":None}
        if state.get("operation") == "delete" and state.get("matches") and _is_confirmation(request.message):
            matches=state["matches"]
            if len(matches)!=1: return {"status":"calendar_delete_confirmation","message":"Znalazłem więcej niż jedno pasujące wydarzenie. Wskaż numer, które usunąć.","event":state}
            _calendar_call(delete_event,matches[0]["id"]); return {"status":"deleted","message":f"Usunięte: {matches[0]['title']}.","event":None}
        if state.get("operation") == "create" and _is_confirmation(request.message):
            if _missing_event(state): return {"status":"needs_input","message":"Brakuje jeszcze danych wydarzenia.","event":state}
            event=_build_event(state); result=_calendar_call(create_event,event,allow_duplicate=bool(state.get("allow_duplicate"))); duplicate=result.get("duplicate") if isinstance(result,dict) else None
            if duplicate and not state.get("allow_duplicate"):
                return {"status":"calendar_duplicate_confirmation","message":f"Takie wydarzenie już istnieje: „{duplicate['title']}” o {duplicate.get('start','?')}. Czy chcesz mimo to dodać kolejne?","event":{**state,"allow_duplicate":True,"duplicate_event":duplicate}}
            _save_learning(request,{"operation":"create","event":state})
            return {"status":"confirmed","message":f"Dodane: {event['title']}.","event":event,"calendar_link":result.get("calendar_link") if isinstance(result,dict) else result}

        if state.get("operation") == "create" and _is_thanks(request.message):
            return {"status":"chat","message":"Nie ma za co!","event":None}

        if _is_calendar_search_intent(request.message):
            previous_search = state.get("search") if state.get("operation") in {"search", "delete"} else None
            criteria = _normalize_search_criteria(_extract_search_criteria(request.message, previous_search))
            events = _calendar_call(_search_calendar, criteria)
            _save_learning(request,{"operation":"search","search":criteria})
            return {"status":"calendar_search","message":_format_events(events),"event":{"operation":"search","search":criteria,"matches":events}}

        history=[item.model_dump() if hasattr(item,"model_dump") else item.dict() for item in request.history]
        result=ask_llm(message=request.message,history=history,draft_event=request.draft_event,user_id=request.user_id)
        operation,status,reply=result.get("operation","chat"),result.get("status","chat"),result.get("reply","")
        if operation=="external_search": return {"status":"external_search","message":"To pytanie dotyczy informacji spoza kalendarza. Nie mam jeszcze podłączonego wyszukiwania internetowego, więc nie będę zgadywać odpowiedzi.","event":None}
        if operation=="search":
            previous_search = state.get("search") if state.get("operation") in {"search", "delete"} else None
            criteria=_normalize_search_criteria(_extract_search_criteria(request.message,_merge_search(previous_search,result.get("search")))); events=_calendar_call(_search_calendar,criteria); _save_learning(request,{"operation":"search","search":criteria}); return {"status":"calendar_search","message":_format_events(events),"event":{"operation":"search","search":criteria,"matches":events}}
        if operation=="delete":
            previous_matches=_last_matches(state); previous_search = state.get("search") if state.get("operation") in {"search","delete"} else None
            criteria=_normalize_search_criteria(_extract_search_criteria(request.message,_merge_search(previous_search,result.get("search")))); events=previous_matches if previous_matches and not any(criteria.values()) else _calendar_call(_search_calendar,criteria)
            if not events: return {"status":"chat","message":"Nie znalazłem pasującego wydarzenia do usunięcia.","event":None}
            if len(events)>1: return {"status":"calendar_delete_confirmation","message":_format_events(events)+"\nKtóre wydarzenie mam usunąć? Podaj numer albo napisz „usuń oba/wszystkie”.","event":{"operation":"delete","search":criteria,"matches":events}}
            event=events[0]; return {"status":"calendar_delete_confirmation","message":f"Znalazłem „{event['title']}” o {event.get('start','?')}. Czy chcesz je usunąć?","event":{"operation":"delete","search":criteria,"matches":[event]}}

        event_data=_merge_event(request.draft_event if state.get("operation","create")=="create" else None,result.get("event"))
        if operation=="create":
            event_data=event_data or {"operation":"create"}; event_data["operation"]="create"
            return {"status":"ready_for_confirmation" if not _missing_event(event_data) else "needs_input","message":reply,"event":event_data}
        return {"status":status,"message":reply,"event":event_data}
    except CalendarAuthRequired as exc:
        return {"status":"calendar_auth_required","message":"Google Calendar wymaga ponownej autoryzacji. Stan operacji został zachowany.","error":str(exc),"event":request.draft_event}
    except (ValueError,json.JSONDecodeError) as exc:
        return {"status":"needs_input","message":str(exc),"event":request.draft_event}
    except Exception as exc:
        return {"status":"error","message":str(exc),"event":request.draft_event}