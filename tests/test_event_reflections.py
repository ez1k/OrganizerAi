import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import reflections
from app.schemas import (
    EventReflectionRequest,
    MotivationReminderRequest,
    MotivationReminderStatusRequest,
)
from app.services.event_reflection_service import _iso_utc, _utc_naive


class EventReflectionServiceHelperTests(unittest.TestCase):
    def test_utc_naive_converts_timezone_aware_datetime(self):
        warsaw_like = timezone(timedelta(hours=2))
        value = datetime(2026, 8, 16, 12, 0, tzinfo=warsaw_like)
        self.assertEqual(_utc_naive(value), datetime(2026, 8, 16, 10, 0))

    def test_iso_utc_marks_sql_datetime_as_utc(self):
        self.assertEqual(_iso_utc(datetime(2026, 8, 16, 10, 0)), "2026-08-16T10:00:00Z")


class EventReflectionRouteTests(unittest.TestCase):
    def _reflection_request(self):
        return EventReflectionRequest(
            calendar_event_id="calendar-event-1",
            event_title="spacer",
            event_start=datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc),
            event_end=datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc),
            rating=5,
            sentiment="positive",
            feedback_text="Było super, dobrze odpocząłem.",
            worth_repeating=True,
            user_id="local-user",
        )

    def test_reflection_endpoint_keeps_event_feedback_separate_from_nlp_feedback(self):
        stored = {
            "id": 7,
            "calendar_event_id": "calendar-event-1",
            "event_title": "spacer",
            "rating": 5,
            "sentiment": "positive",
            "worth_repeating": True,
        }
        request = self._reflection_request()

        with patch.object(reflections, "save_event_reflection", return_value=stored) as save:
            result = reflections.create_or_update_reflection(request)

        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["reflection"], stored)
        save.assert_called_once()
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["feedback_text"], "Było super, dobrze odpocząłem.")
        self.assertTrue(kwargs["worth_repeating"])

    def test_reminder_requires_owned_reflection(self):
        request = MotivationReminderRequest(
            remind_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
            user_id="local-user",
        )
        with patch.object(reflections, "schedule_motivation_reminder", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                reflections.create_motivation_reminder(999, request)

        self.assertEqual(ctx.exception.status_code, 404)

    def test_due_endpoint_only_returns_pending_suggestions(self):
        due = [
            {
                "id": 3,
                "reflection_id": 7,
                "status": "pending",
                "event_title": "spacer",
                "worth_repeating": True,
            }
        ]
        with patch.object(reflections, "list_due_motivation_reminders", return_value=due) as load:
            result = reflections.get_due_motivation_reminders("local-user", 20)

        self.assertEqual(result, {"reminders": due})
        load.assert_called_once_with("local-user", limit=20)

    def test_reminder_status_endpoint_does_not_create_calendar_event(self):
        reminder = {
            "id": 3,
            "reflection_id": 7,
            "status": "delivered",
            "event_title": "spacer",
        }
        request = MotivationReminderStatusRequest(status="delivered", user_id="local-user")

        with patch.object(
            reflections,
            "update_motivation_reminder_status",
            return_value=reminder,
        ) as update:
            result = reflections.set_motivation_reminder_status(3, request)

        self.assertEqual(result["status"], "delivered")
        update.assert_called_once_with(
            user_id="local-user",
            reminder_id=3,
            status="delivered",
        )


if __name__ == "__main__":
    unittest.main()
