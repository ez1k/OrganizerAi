import unittest
from unittest.mock import patch

from app.routes import chat_flow
from app.schemas import ChatRequest


class CreateDelimitedFormatTests(unittest.TestCase):
    def _request(self, message, draft=None):
        return ChatRequest(
            message=message,
            history=[],
            draft_event=draft,
            user_id="local-user",
            session_id="delimited-create-test",
        )

    def test_delimited_create_uses_middle_segment_as_title(self):
        messages = (
            "dodaj na jutro 12:00 - gra w valorant - 90 min",
            "dodaj jutro 12:00 - gra w valorant - 90 min",
            "dodaj 16.08.2026 o 12:00 - gra w valorant - 90 min",
        )

        for message in messages:
            with self.subTest(message=message), (
                patch.object(chat_flow.chat, "chat_endpoint") as delegated,
                patch.object(chat_flow, "save_chat_turn_metric"),
            ):
                result = chat_flow.chat_endpoint(self._request(message))

            self.assertEqual(result["status"], "ready_for_confirmation")
            self.assertEqual(result["event"]["title"], "gra w valorant")
            self.assertEqual(result["event"]["time_hint"], "12:00")
            self.assertEqual(result["event"]["duration_minutes"], 90)
            self.assertIn("gra w valorant", result["message"])
            delegated.assert_not_called()

    def test_original_problematic_message_keeps_relative_date(self):
        with patch.object(chat_flow, "save_chat_turn_metric"):
            result = chat_flow.chat_endpoint(
                self._request("dodaj na jutro 12:00 - gra w valorant - 90 min")
            )

        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertNotEqual(result["event"]["title"], "na")

    def test_unparseable_term_never_escapes_fast_path_as_server_error(self):
        draft = {
            "operation": "create",
            "title": "gra w valorant",
            "date_hint": "nieznany-dzień",
            "time_hint": "12:00",
            "duration_minutes": 45,
        }

        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("90 min", draft))

        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["event"]["title"], "gra w valorant")
        self.assertEqual(result["event"]["duration_minutes"], 90)
        self.assertNotIn("date_hint", result["event"])
        self.assertNotIn("time_hint", result["event"])
        self.assertIn("bezpiecznie rozpoznać terminu", result["message"])
        delegated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
