import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.summary_service import _top_activities, _weekly_activity


WARSAW = ZoneInfo("Europe/Warsaw")


class SummaryServiceTests(unittest.TestCase):
    def test_top_activities_aggregates_titles_case_insensitively(self):
        reflections = [
            {
                "event_title": "Bieganie",
                "rating": 5,
                "worth_repeating": True,
                "event_end": datetime(2026, 8, 30, 10, 0),
            },
            {
                "event_title": "bieganie",
                "rating": 4,
                "worth_repeating": True,
                "event_end": datetime(2026, 8, 29, 10, 0),
            },
            {
                "event_title": "Nauka",
                "rating": 3,
                "worth_repeating": False,
                "event_end": datetime(2026, 8, 28, 10, 0),
            },
        ]

        result = _top_activities(reflections)

        self.assertEqual(result[0]["title"], "Bieganie")
        self.assertEqual(result[0]["reflection_count"], 2)
        self.assertEqual(result[0]["worth_repeating_count"], 2)
        self.assertEqual(result[0]["average_rating"], 4.5)

    def test_weekly_activity_counts_calendar_events(self):
        now = datetime.now(WARSAW)
        events = [
            {
                "title": "Spacer",
                "start": now.isoformat(),
                "end": now.isoformat(),
            }
        ]

        result = _weekly_activity(events, 30)

        self.assertTrue(result)
        self.assertEqual(sum(item["count"] for item in result), 1)


if __name__ == "__main__":
    unittest.main()
