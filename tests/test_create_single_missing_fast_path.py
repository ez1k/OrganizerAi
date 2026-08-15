import unittest
from unittest.mock import patch

from app.routes import chat_flow
from app.schemas import ChatRequest


class CreateSingleMissingFastPathTests(unittest.TestCase):
    @staticmethod
    def _request(message):
        return ChatRequest(
            message=message,
            history=[],
            draft_event=None,
            user_id="local-user",
            session_id="single-missing-test",
        )

    def test_missing_duration_bypasses_core_router(self):
        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("dodaj trening jutro o 17")
            )

        self.assertEqual(result["status"], "needs_input")
        self.assertIn("czasu trwania", result["message"])
        self.assertEqual(result["event"]["title"], "trening")
        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertEqual(result["event"]["time_hint"], "17:00")
        self.assertNotIn("duration_minutes", result["event"])
        delegated.assert_not_called()

    def test_missing_date_bypasses_core_router(self):
        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("dodaj trening o 17 na 60 min")
            )

        self.assertEqual(result["status"], "needs_input")
        self.assertIn("dnia", result["message"])
        self.assertEqual(result["event"]["title"], "trening")
        self.assertEqual(result["event"]["time_hint"], "17:00")
        self.assertEqual(result["event"]["duration_minutes"], 60)
        delegated.assert_not_called()

    def test_missing_time_bypasses_core_router(self):
        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("dodaj trening jutro na 60 min")
            )

        self.assertEqual(result["status"], "needs_input")
        self.assertIn("godziny rozpoczęcia", result["message"])
        self.assertEqual(result["event"]["title"], "trening")
        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertEqual(result["event"]["duration_minutes"], 60)
        delegated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
