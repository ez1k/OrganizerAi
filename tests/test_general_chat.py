import unittest
from unittest.mock import patch

from app.routes import chat
from app.schemas import ChatRequest


class GeneralChatTests(unittest.TestCase):
    def _request(self, message, draft=None):
        return ChatRequest(
            message=message,
            history=[],
            draft_event=draft,
            user_id="local-user",
            session_id="general-chat-test",
        )

    def test_general_chat_returns_model_reply_without_calendar_event(self):
        with patch.object(
            chat,
            "ask_llm",
            return_value={
                "operation": "chat",
                "status": "chat",
                "reply": "Jasne — 4 × 4 = 16.",
                "event": {"title": "nie powinno trafić do draftu"},
            },
        ):
            result = chat.chat_endpoint(
                self._request("czy możesz pomnożyć 4x4?")
            )

        self.assertEqual(result["status"], "chat")
        self.assertEqual(result["message"], "Jasne — 4 × 4 = 16.")
        self.assertIsNone(result["event"])

    def test_topic_change_does_not_mutate_active_create_draft(self):
        draft = {
            "operation": "create",
            "title": "trening",
            "date_hint": "jutro",
        }
        with patch.object(
            chat,
            "ask_llm",
            return_value={
                "operation": "chat",
                "status": "chat",
                "reply": "16.",
            },
        ):
            result = chat.chat_endpoint(
                self._request("ile to 4x4?", draft=draft)
            )

        self.assertEqual(result["status"], "chat")
        self.assertEqual(result["message"], "16.")
        self.assertIsNone(result["event"])

    def test_external_search_message_is_reserved_for_fresh_data(self):
        with patch.object(
            chat,
            "ask_llm",
            return_value={
                "operation": "external_search",
                "status": "external_search",
                "reply": "",
            },
        ):
            result = chat.chat_endpoint(
                self._request("jaka jest teraz pogoda?")
            )

        self.assertEqual(result["status"], "external_search")
        self.assertIn("aktualnych danych zewnętrznych", result["message"])
        self.assertIsNone(result["event"])


if __name__ == "__main__":
    unittest.main()
