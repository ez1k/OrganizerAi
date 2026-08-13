import unittest
from unittest.mock import patch

from app.routes import chat
from app.schemas import ChatRequest


class CreateFlowTests(unittest.TestCase):
    @staticmethod
    def _request(message, draft_event=None):
        return ChatRequest(
            message=message,
            history=[],
            draft_event=draft_event,
            user_id="local-user",
        )

    @staticmethod
    def _llm_result(operation="chat", event=None):
        return {
            "operation": operation,
            "status": "chat",
            "reply": "model reply",
            "event": event,
        }

    @staticmethod
    def _complete_draft(**overrides):
        draft = {
            "operation": "create",
            "title": "trening siłowy",
            "date_hint": "jutro",
            "time_hint": "17:00",
            "duration_minutes": 90,
        }
        draft.update(overrides)
        return draft

    @staticmethod
    def _built_event(title="trening siłowy"):
        return {
            "title": title,
            "description": "",
            "start": "2026-08-14T17:00:00+02:00",
            "end": "2026-08-14T18:30:00+02:00",
        }

    def test_initial_create_requires_duration_even_if_llm_invents_default(self):
        llm_event = {
            "title": "trening siłowy",
            "date_hint": "jutro",
            "time_hint": "17:00",
            "duration_minutes": 60,
        }
        with patch.object(chat, "ask_llm", return_value=self._llm_result("create", llm_event)):
            result = chat.chat_endpoint(
                self._request("hej, chce dodać trening siłowy na jutro 17")
            )

        self.assertEqual(result["status"], "needs_input")
        self.assertIn("czasu trwania", result["message"])
        self.assertEqual(result["event"]["title"], "trening siłowy")
        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertEqual(result["event"]["time_hint"], "17:00")
        self.assertNotIn("duration_minutes", result["event"])

    def test_continuation_updates_title_when_duration_comes_first(self):
        draft = self._complete_draft(duration_minutes=None)
        with (
            patch.object(chat, "ask_llm", return_value=self._llm_result()),
            patch.object(chat, "_create_confirmation_message", return_value="summary"),
        ):
            result = chat.chat_endpoint(self._request("90 min, trening nóg", draft))

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["message"], "summary")
        self.assertEqual(result["event"]["title"], "trening nóg")
        self.assertEqual(result["event"]["duration_minutes"], 90)
        self.assertEqual(result["event"]["time_hint"], "17:00")

    def test_continuation_updates_title_when_title_comes_first(self):
        draft = self._complete_draft(duration_minutes=None)
        with (
            patch.object(chat, "ask_llm", return_value=self._llm_result()),
            patch.object(chat, "_create_confirmation_message", return_value="summary"),
        ):
            result = chat.chat_endpoint(self._request("trening nóg, 90 min", draft))

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["event"]["title"], "trening nóg")
        self.assertEqual(result["event"]["duration_minutes"], 90)

    def test_time_correction_preserves_other_create_slots(self):
        draft = self._complete_draft()
        with (
            patch.object(chat, "ask_llm", return_value=self._llm_result()),
            patch.object(chat, "_create_confirmation_message", return_value="summary"),
        ):
            result = chat.chat_endpoint(self._request("jednak o 18", draft))

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["event"]["time_hint"], "18:00")
        self.assertEqual(result["event"]["title"], "trening siłowy")
        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertEqual(result["event"]["duration_minutes"], 90)

    def test_confirmation_with_missing_duration_never_calls_calendar(self):
        draft = self._complete_draft()
        draft.pop("duration_minutes")

        with patch.object(chat, "create_event") as create_event_mock:
            result = chat.chat_endpoint(self._request("ok dodaj", draft))

        self.assertEqual(result["status"], "needs_input")
        self.assertIn("czasu trwania", result["message"])
        create_event_mock.assert_not_called()

    def test_complete_confirmation_calls_calendar_once(self):
        draft = self._complete_draft()
        built = self._built_event()

        with (
            patch.object(chat, "_build_event", return_value=built),
            patch.object(
                chat,
                "create_event",
                return_value={"calendar_link": "https://calendar.example/event"},
            ) as create_event_mock,
            patch.object(chat, "_save_learning"),
        ):
            result = chat.chat_endpoint(self._request("ok dodaj", draft))

        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(result["message"].startswith("Dodane do Google Calendar:"))
        self.assertEqual(result["calendar_link"], "https://calendar.example/event")
        create_event_mock.assert_called_once_with(built, allow_duplicate=False)

    def test_duplicate_requires_another_confirmation(self):
        draft = self._complete_draft()
        built = self._built_event()
        duplicate = {
            "id": "existing-event",
            "title": "trening siłowy",
            "start": "2026-08-14T17:00:00+02:00",
        }

        with (
            patch.object(chat, "_build_event", return_value=built),
            patch.object(chat, "create_event", return_value={"duplicate": duplicate}),
        ):
            first = chat.chat_endpoint(self._request("tak", draft))

        self.assertEqual(first["status"], "calendar_duplicate_confirmation")
        self.assertTrue(first["event"]["allow_duplicate"])

        with (
            patch.object(chat, "_build_event", return_value=built),
            patch.object(
                chat,
                "create_event",
                return_value={"calendar_link": "https://calendar.example/duplicate"},
            ) as create_event_mock,
            patch.object(chat, "_save_learning"),
        ):
            second = chat.chat_endpoint(self._request("dawaj", first["event"]))

        self.assertEqual(second["status"], "confirmed")
        create_event_mock.assert_called_once_with(built, allow_duplicate=True)

    def test_status_question_never_claims_uncommitted_create(self):
        draft = self._complete_draft()
        with patch.object(chat, "create_event") as create_event_mock:
            result = chat.chat_endpoint(self._request("na pewno dodałeś?", draft))

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertTrue(result["message"].startswith("Nie."))
        create_event_mock.assert_not_called()

    def test_common_confirmation_phrases_are_supported(self):
        for message in ("tak", "ok dodaj", "dawaj", "no dodaj", "dodawaj"):
            with self.subTest(message=message):
                self.assertTrue(chat._is_confirmation(message))


if __name__ == "__main__":
    unittest.main()
