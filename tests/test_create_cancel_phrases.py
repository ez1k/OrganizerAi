import unittest
from unittest.mock import patch

from app.routes import chat_flow
from app.schemas import ChatRequest


class CreateCancelPhraseTests(unittest.TestCase):
    def _request(self, message):
        return ChatRequest(
            message=message,
            history=[],
            draft_event={
                "operation": "create",
                "title": "trening",
                "date_hint": "jutro",
                "time_hint": "17:00",
            },
            user_id="local-user",
            session_id="cancel-phrase-test",
        )

    def test_natural_cancel_phrases_clear_create_draft_without_core_router(self):
        phrases = (
            "albo nieważne jednak",
            "jednak nieważne",
            "a dobra nieważne",
            "w sumie odpuść",
            "dobra anuluj",
            "nie dodawaj jednak",
        )

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                with (
                    patch.object(chat_flow.chat, "chat_endpoint") as delegated,
                    patch.object(chat_flow, "save_chat_turn_metric"),
                ):
                    result = chat_flow.chat_endpoint(self._request(phrase))

                self.assertEqual(result["status"], "cancelled")
                self.assertIsNone(result["event"])
                self.assertIn("Anulowano", result["message"])
                delegated.assert_not_called()

    def test_cancel_matcher_does_not_consume_new_create_instruction(self):
        self.assertFalse(
            chat_flow._is_create_cancel("nieważne, dodaj jutro o 18")
        )


if __name__ == "__main__":
    unittest.main()
