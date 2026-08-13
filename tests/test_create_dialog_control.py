import unittest
from unittest.mock import patch

from app.routes import chat_flow
from app.schemas import ChatRequest


class CreateDialogControlTests(unittest.TestCase):
    def _request(self, message, draft):
        return ChatRequest(message=message, history=[], draft_event=draft, user_id="local-user")

    def _draft(self):
        return {
            "operation": "create",
            "title": "trening siłowy",
            "date_hint": "jutro",
            "time_hint": "17:00",
            "duration_minutes": 90,
        }

    def test_no_keeps_draft_for_correction(self):
        draft = self._draft()
        with patch.object(chat_flow.chat, "chat_endpoint") as delegated:
            result = chat_flow.chat_endpoint(self._request("nie", draft))
        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["event"], draft)
        delegated.assert_not_called()

    def test_cancel_clears_draft(self):
        draft = self._draft()
        with patch.object(chat_flow.chat, "chat_endpoint") as delegated:
            result = chat_flow.chat_endpoint(self._request("anuluj", draft))
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["event"])
        delegated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
