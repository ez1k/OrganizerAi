from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

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
        body=gcal_event
    ).execute()

    return created_event.get("htmlLink")