import unittest
from unittest.mock import patch

from app.routes import chat, chat_flow
from app.schemas import ChatRequest


class DeleteFlowTests(unittest.TestCase):
    @staticmethod
    def _request(message, draft=None):
        return ChatRequest(
            message=message,
            history=[],
            draft_event=draft,
            user_id="local-user",
            session_id="delete-test-session",
        )

    @staticmethod
    def _event(event_id="event-1", title="dentysta", hour=18):
        return {
            "id": event_id,
            "title": title,
            "description": "",
            "start": f"2026-08-16T{hour:02d}:00:00+02:00",
            "end": f"2026-08-16T{hour:02d}:45:00+02:00",
        }

    def test_delete_search_with_one_match_stops_before_delete(self):
        event = self._event()
        llm_result = {
            "operation": "delete",
            "status": "calendar_delete_confirmation",
            "reply": "",
            "search": {"title": "dentysta", "date_hint": "jutro"},
        }

        with (
            patch.object(chat, "ask_llm", return_value=llm_result),
            patch.object(chat, "_search_calendar", return_value=[event]),
            patch.object(chat, "delete_event") as delete_event_mock,
        ):
            result = chat.chat_endpoint(self._request("usuń dentystę jutro"))

        self.assertEqual(result["status"], "calendar_delete_confirmation")
        self.assertEqual(result["event"]["operation"], "delete")
        self.assertEqual(result["event"]["matches"], [event])
        delete_event_mock.assert_not_called()

    def test_deterministic_delete_fast_path_strips_trailing_day(self):
        event = self._event(title="dentystę")

        with (
            patch.object(chat_flow.chat, "_search_calendar", return_value=[event]) as search_mock,
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("usuń dentystę jutro"))

        self.assertEqual(result["status"], "calendar_delete_confirmation")
        self.assertEqual(result["event"]["operation"], "delete")
        criteria = search_mock.call_args.args[0]
        self.assertEqual(criteria["title"], "dentystę")
        self.assertEqual(criteria["date_hint"], "jutro")
        delegated.assert_not_called()

    def test_deterministic_delete_no_match_bypasses_llm(self):
        with (
            patch.object(chat_flow.chat, "_search_calendar", return_value=[]),
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric") as save_metric,
        ):
            result = chat_flow.chat_endpoint(
                self._request("usuń wydarzenie benchmark-nieistniejace-7f3a jutro")
            )

        self.assertEqual(result["status"], "calendar_delete_not_found")
        self.assertIsNone(result["event"])
        delegated.assert_not_called()
        self.assertEqual(save_metric.call_args.kwargs["operation"], "delete")
        self.assertEqual(save_metric.call_args.kwargs["llm_calls"], 0)

    def test_number_selection_reduces_multiple_matches_without_delete(self):
        first = self._event("event-1", "dentysta", 17)
        second = self._event("event-2", "dentysta", 18)
        draft = {"operation": "delete", "search": {}, "matches": [first, second]}

        with patch.object(chat, "delete_event") as delete_event_mock:
            result = chat.chat_endpoint(self._request("2", draft))

        self.assertEqual(result["status"], "calendar_delete_confirmation")
        self.assertEqual(result["event"]["matches"], [second])
        self.assertEqual(result["event"]["selected_event_id"], "event-2")
        delete_event_mock.assert_not_called()

    def test_delete_all_requires_separate_confirmation(self):
        events = [
            self._event("event-1", "trening", 17),
            self._event("event-2", "trening", 18),
        ]
        draft = {"operation": "delete", "search": {}, "matches": events}

        with patch.object(chat, "delete_event") as delete_event_mock:
            result = chat.chat_endpoint(self._request("usuń wszystkie", draft))

        self.assertEqual(result["status"], "calendar_delete_confirmation")
        self.assertTrue(result["event"]["delete_all"])
        delete_event_mock.assert_not_called()

    def test_plain_confirmation_with_multiple_matches_does_not_delete(self):
        events = [
            self._event("event-1", "trening", 17),
            self._event("event-2", "trening", 18),
        ]
        draft = {"operation": "delete", "search": {}, "matches": events}

        with patch.object(chat, "delete_event") as delete_event_mock:
            result = chat.chat_endpoint(self._request("tak", draft))

        self.assertEqual(result["status"], "calendar_delete_confirmation")
        self.assertIn("Wskaż numer", result["message"])
        delete_event_mock.assert_not_called()

    def test_explicit_single_delete_confirmation_calls_delete_once(self):
        event = self._event()
        draft = {"operation": "delete", "search": {}, "matches": [event]}

        with (
            patch.object(chat_flow.chat, "chat_endpoint", return_value={
                "status": "deleted",
                "message": "Usunięte: dentysta.",
                "event": None,
            }) as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("tak usuń", draft))

        self.assertEqual(result["status"], "deleted")
        delegated.assert_called_once()
        delegated_request = delegated.call_args.args[0]
        self.assertEqual(delegated_request.message, "tak")

    def test_ambiguous_dawaj_never_reaches_delete_core(self):
        event = self._event()
        draft = {"operation": "delete", "search": {}, "matches": [event]}

        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("dawaj", draft))

        self.assertEqual(result["status"], "calendar_delete_confirmation")
        self.assertIn("bezpieczeństwa", result["message"])
        self.assertEqual(result["event"], draft)
        delegated.assert_not_called()

    def test_delete_decline_cancels_and_clears_state(self):
        event = self._event()
        draft = {"operation": "delete", "search": {}, "matches": [event]}

        for phrase in ("nie", "jednak nie", "anuluj", "nieważne", "nie usuwaj"):
            with self.subTest(phrase=phrase):
                with (
                    patch.object(chat_flow.chat, "chat_endpoint") as delegated,
                    patch.object(chat_flow, "save_chat_turn_metric"),
                ):
                    result = chat_flow.chat_endpoint(self._request(phrase, draft))

                self.assertEqual(result["status"], "cancelled")
                self.assertIsNone(result["event"])
                delegated.assert_not_called()

    def test_core_single_confirmation_calls_delete_once(self):
        event = self._event()
        draft = {"operation": "delete", "search": {}, "matches": [event]}

        with patch.object(chat, "delete_event") as delete_event_mock:
            result = chat.chat_endpoint(self._request("tak", draft))

        self.assertEqual(result["status"], "deleted")
        delete_event_mock.assert_called_once_with("event-1")


if __name__ == "__main__":
    unittest.main()
