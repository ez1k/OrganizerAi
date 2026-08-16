import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.routes import reflections
from app.schemas import MotivationReminderNaturalRequest
from app.services.motivation_time_service import parse_motivation_reminder_time


WARSAW = ZoneInfo("Europe/Warsaw")


class MotivationTimeParserTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 15, 23, 30, tzinfo=WARSAW)

    def test_two_weeks_in_polish(self):
        parsed = parse_motivation_reminder_time("za dwa tygodnie", now=self.now)
        self.assertEqual(parsed, datetime(2026, 8, 29, 23, 30, tzinfo=WARSAW))

    def test_month_uses_calendar_month(self):
        parsed = parse_motivation_reminder_time("przypomnij za miesiąc", now=self.now)
        self.assertEqual(parsed, datetime(2026, 9, 15, 23, 30, tzinfo=WARSAW))

    def test_minutes_are_supported_for_quick_manual_testing(self):
        parsed = parse_motivation_reminder_time("za 15 minut", now=self.now)
        self.assertEqual(parsed, datetime(2026, 8, 15, 23, 45, tzinfo=WARSAW))

    def test_vague_phrase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Nie rozumiem terminu"):
            parse_motivation_reminder_time("kiedyś", now=self.now)


class MotivationReminderRouteTests(unittest.TestCase):
    def test_natural_endpoint_parses_then_schedules(self):
        request = MotivationReminderNaturalRequest(
            when_text="za 2 tygodnie",
            user_id="local-user",
        )
        parsed = datetime(2026, 8, 29, 23, 30, tzinfo=WARSAW)
        reminder = {
            "id": 7,
            "reflection_id": 2,
            "status": "pending",
            "event_title": "spacer",
            "remind_at": "2026-08-29T21:30:00Z",
        }

        with (
            patch.object(reflections, "parse_motivation_reminder_time", return_value=parsed) as parse_time,
            patch.object(reflections, "schedule_motivation_reminder", return_value=reminder) as schedule,
        ):
            result = reflections.create_motivation_reminder_from_text(2, request)

        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["reminder"], reminder)
        parse_time.assert_called_once_with("za 2 tygodnie")
        schedule.assert_called_once_with(
            user_id="local-user",
            reflection_id=2,
            remind_at=parsed,
        )


if __name__ == "__main__":
    unittest.main()
