from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
import os
import pickle

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"


def _save_credentials(creds):
    with open(TOKEN_FILE, "wb") as token:
        pickle.dump(creds, token)


def _run_oauth_flow():
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Brak pliku {CREDENTIALS_FILE}. Umieść plik OAuth Client credentials "
            "w katalogu, z którego uruchamiana jest aplikacja."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        SCOPES,
    )
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
            # A corrupted token file is equivalent to having no credentials.
            try:
                os.remove(TOKEN_FILE)
            except OSError:
                pass
            creds = None

    if creds and creds.valid:
        return build("calendar", "v3", credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return build("calendar", "v3", credentials=creds)
        except RefreshError:
            # Google rejected the refresh token (for example invalid_grant).
            # Remove the unusable cached credentials and start OAuth again.
            try:
                os.remove(TOKEN_FILE)
            except OSError:
                pass

    creds = _run_oauth_flow()
    return build("calendar", "v3", credentials=creds)


def create_event(event: dict):
    service = get_calendar_service()

    gcal_event = {
        "summary": event["title"],
        "description": event.get("description", ""),
        "start": {
            "dateTime": event["start"],
            "timeZone": "Europe/Warsaw",
        },
        "end": {
            "dateTime": event["end"],
            "timeZone": "Europe/Warsaw",
        },
    }

    created_event = service.events().insert(
        calendarId="primary",
        body=gcal_event,
    ).execute()

    return created_event.get("htmlLink")
