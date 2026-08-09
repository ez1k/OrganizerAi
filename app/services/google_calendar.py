from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
import logging
import os
import pickle

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"
CALENDAR_TZ = ZoneInfo("Europe/Warsaw")
logger = logging.getLogger(__name__)


def _save_credentials(creds):
    with open(TOKEN_FILE, "wb") as token:
        pickle.dump(creds, token)


def _run_oauth_flow():
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Brak pliku {CREDENTIALS_FILE}. Umieść plik OAuth Client credentials w katalogu, z którego uruchamiana jest aplikacja.")
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "rb") as token:
                creds = pickle.load(token)
        except (EOFError, pickle.PickleError, AttributeError, ValueError, TypeError):
            try: os.remove(TOKEN_FILE)
            except OSError: pass
    if creds and creds.valid:
        return build("calendar", "v3", credentials=creds)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return build("calendar", "v3", credentials=creds)
        except RefreshError:
            try: os.remove(TOKEN_FILE)
            except OSError: pass
    return build("calendar", "v3", credentials=_run_oauth_flow())


def _event_datetime(value: str | None):
    if not value: return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=CALENDAR_TZ)
    except ValueError: return None


def _calendar_datetime(value: datetime) -> str:
    if value.tzinfo is None: value = value.replace(tzinfo=CALENDAR_TZ)
    return value.astimezone(CALENDAR_TZ).isoformat()


def create_event(event: dict, allow_duplicate: bool = False):
    service = get_calendar_service()
    gcal_event = {
        "summary": event["title"],
        "description": event.get("description", ""),
        "start": {"dateTime": event["start"], "timeZone": "Europe/Warsaw"},
        "end": {"dateTime": event["end"], "timeZone": "Europe/Warsaw"},
    }
    if not allow_duplicate:
        duplicates = find_duplicate_events(event)
        if duplicates: return {"duplicate": duplicates[0]}
    created_event = service.events().insert(calendarId="primary", body=gcal_event).execute()
    return {"calendar_link": created_event.get("htmlLink")}


def search_events(title: str | None = None, start: datetime | None = None, end: datetime | None = None, max_results: int = 100) -> list[dict]:
    """Find events and log the exact Google Calendar request/response for diagnostics."""
    service = get_calendar_service()
    start = start or datetime.now(CALENDAR_TZ)
    end = end or (start + timedelta(days=30))
    if start.tzinfo is None: start = start.replace(tzinfo=CALENDAR_TZ)
    if end.tzinfo is None: end = end.replace(tzinfo=CALENDAR_TZ)

    base_params = {
        "calendarId": "primary",
        "timeMin": _calendar_datetime(start),
        "timeMax": _calendar_datetime(end),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": min(max_results, 2500),
    }
    if title: base_params["q"] = title.strip()

    logger.warning("CALENDAR SEARCH params=%s", base_params)
    events = []
    page_token = None
    page = 0
    while True:
        params = dict(base_params)
        if page_token: params["pageToken"] = page_token
        page += 1
        response = service.events().list(**params).execute()
        items = response.get("items", [])
        logger.warning("CALENDAR SEARCH page=%s items=%s nextPageToken=%s", page, len(items), bool(response.get("nextPageToken")))
        for item in items:
            start_data, end_data = item.get("start", {}), item.get("end", {})
            parsed = {
                "id": item.get("id"),
                "title": item.get("summary", ""),
                "description": item.get("description", ""),
                "start": start_data.get("dateTime") or start_data.get("date"),
                "end": end_data.get("dateTime") or end_data.get("date"),
                "calendar_link": item.get("htmlLink"),
            }
            logger.warning("CALENDAR EVENT id=%s title=%r start=%s end=%s", parsed["id"], parsed["title"], parsed["start"], parsed["end"])
            events.append(parsed)
        page_token = response.get("nextPageToken")
        if not page_token or len(events) >= max_results: break
    logger.warning("CALENDAR SEARCH total=%s", len(events))
    return events[:max_results]


def find_duplicate_events(event: dict) -> list[dict]:
    start, end = _event_datetime(event.get("start")), _event_datetime(event.get("end"))
    if not start or not end: return []
    candidates = search_events(title=event.get("title"), start=start-timedelta(minutes=1), end=end+timedelta(minutes=1), max_results=20)
    return [e for e in candidates if e.get("title", "").strip().casefold() == event.get("title", "").strip().casefold() and _event_datetime(e.get("start")) == start and _event_datetime(e.get("end")) == end]


def delete_event(event_id: str):
    get_calendar_service().events().delete(calendarId="primary", eventId=event_id).execute()
