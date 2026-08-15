import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.routes import events
from app.services import google_calendar


class RecentCompletedCalendarEventsTests(unittest.TestCase):
    def test_recent_completed_events_filter_future_and_normalize(self):
        now = datetime.now(google_calendar.CALENDAR_TZ)
        past_start = now - timedelta(hours=3)
        past_end = now - timedelta(hours=2)
        future_end = now + timedelta(hours=1)

        candidates = [
            {
                "id": "done-1",
                "title": "Spacer",
                "start": past_start.isoformat(),
                "end": past_end.isoformat(),
                "calendar_link": "https://example.test/done",
            },
            {
                "id": "still-running",
                "title": "Długie spotkanie",
                "start": past_start.isoformat(),
                "end": future_end.isoformat(),
                "calendar_link": None,
            },
            {
                "id": None,
                "title": "Bez ID",
                "start": past_start.isoformat(),
                "end": past_end.isoformat(),
            },
        ]

        with patch.object(google_calendar, "search_events", return_value=candidates):
            result = google_calendar.list_recent_completed_events(days=14, max_results=20)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "done-1")
        self.assertEqual(result[0]["title"], "Spacer")
        self.assertIn("+", result[0]["start"])
        self.assertIn("+", result[0]["end"])

    def test_all_day_event_is_normalized_to_datetime(self):
        yesterday = datetime.now(google_calendar.CALENDAR_TZ).date() - timedelta(days=1)
        today = yesterday + timedelta(days=1)
        candidates = [
            {
                "id": "all-day",
                "title": "Dzień offline",
                "start": yesterday.isoformat(),
                "end": today.isoformat(),
                "calendar_link": None,
            }
        ]

        with patch.object(google_calendar, "search_events", return_value=candidates):
            result = google_calendar.list_recent_completed_events(days=14, max_results=20)

        self.assertEqual(len(result), 1)
        self.assertIn("T00:00:00", result[0]["start"])
        self.assertIn("T00:00:00", result[0]["end"])


class CompletedEventsRouteTests(unittest.TestCase):
    def test_route_marks_events_already_reflected(self):
        calendar_events = [
            {"id": "rated", "title": "Spacer", "start": "2026-08-14T10:00:00+02:00", "end": "2026-08-14T11:00:00+02:00"},
            {"id": "new", "title": "Trening", "start": "2026-08-14T12:00:00+02:00", "end": "2026-08-14T13:00:00+02:00"},
        ]
        reflections = [
            {"calendar_event_id": "rated"},
        ]

        with (
            patch.object(events, "list_recent_completed_events", return_value=calendar_events),
            patch.object(events, "list_event_reflections", return_value=reflections),
        ):
            result = events.list_completed_events(user_id="local-user", days=14, limit=20)

        by_id = {item["id"]: item for item in result["events"]}
        self.assertTrue(by_id["rated"]["reflected"])
        self.assertFalse(by_id["new"]["reflected"])


if __name__ == "__main__":
    unittest.main()
