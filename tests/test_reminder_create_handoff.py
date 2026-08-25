import unittest
from unittest.mock import patch

from app.routes import chat_flow
from app.schemas import ChatRequest


class ReminderCreateHandoffTests(unittest.TestCase):
    def _request(self, message: str, draft: dict) -> ChatRequest:
        return ChatRequest(
            message=message,
            history=[],
            draft_event=draft,
            user_id="local-user",
            session_id="reminder-handoff-test",
        )

    def test_slot_only_continuation_preserves_reminder_title(self):
        draft = {
            "operation": "create",
            "title": "spacer testowy E2E",
        }

        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow.chat, "_create_confirmation_message", return_value="summary"),
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("jutro o 18 na 30 min", draft)
            )

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["message"], "summary")
        self.assertEqual(result["event"]["title"], "spacer testowy E2E")
        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertEqual(result["event"]["time_hint"], "18:00")
        self.assertEqual(result["event"]["duration_minutes"], 30)
        delegated.assert_not_called()

    def test_partial_slot_continuation_keeps_title_and_stays_deterministic(self):
        draft = {
            "operation": "create",
            "title": "spacer testowy E2E",
        }

        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("jutro", draft))

        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["event"]["title"], "spacer testowy E2E")
        self.assertEqual(result["event"]["date_hint"], "jutro")
        self.assertNotIn("time_hint", result["event"])
        self.assertNotIn("duration_minutes", result["event"])
        delegated.assert_not_called()

    def test_explicit_new_create_can_replace_existing_title(self):
        draft = {
            "operation": "create",
            "title": "spacer testowy E2E",
        }

        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow.chat, "_create_confirmation_message", return_value="summary"),
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("zaplanuj bieganie jutro o 18 na 30 min", draft)
            )

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["event"]["title"], "bieganie")
        delegated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
