import unittest
from unittest.mock import patch

from app.routes import chat_flow
from app.schemas import ChatRequest


class CreateDialogControlTests(unittest.TestCase):
    def _request(self, message, draft=None, session_id="test-session"):
        return ChatRequest(
            message=message,
            history=[],
            draft_event=draft,
            user_id="local-user",
            session_id=session_id,
        )

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
        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("nie", draft))

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["event"], draft)
        delegated.assert_not_called()

    def test_cancel_clears_draft(self):
        draft = self._draft()
        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("anuluj", draft))

        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["event"])
        delegated.assert_not_called()

    def test_colloquial_day_na_hour_is_added_to_create_draft(self):
        llm_result = {
            "operation": "chat",
            "status": "chat",
            "reply": "model reply",
            "event": None,
        }
        with (
            patch.object(chat_flow.chat, "ask_llm", return_value=llm_result),
            patch.object(chat_flow.chat, "_create_confirmation_message", return_value="summary"),
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("to może dodaj siłownie na dziś na 16 - 90 min")
            )

        self.assertEqual(result["status"], "ready_for_confirmation")
        self.assertEqual(result["message"], "summary")
        self.assertEqual(result["event"]["title"], "siłownie")
        self.assertEqual(result["event"]["date_hint"], "dziś")
        self.assertEqual(result["event"]["time_hint"], "16:00")
        self.assertEqual(result["event"]["duration_minutes"], 90)

    def test_tak_dodaj_is_normalized_before_core_router(self):
        draft = self._draft()
        delegated_result = {
            "status": "confirmed",
            "message": "Dodane.",
            "event": {"title": "trening siłowy"},
        }
        with (
            patch.object(chat_flow.chat, "chat_endpoint", return_value=delegated_result) as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(self._request("tak dodaj", draft))

        self.assertEqual(result, delegated_result)
        delegated.assert_called_once()
        delegated_request = delegated.call_args.args[0]
        self.assertEqual(delegated_request.message, "tak")
        self.assertEqual(delegated_request.draft_event, draft)

    def test_natural_duplicate_decline_cancels_without_core_router(self):
        draft = {**self._draft(), "allow_duplicate": True}
        with (
            patch.object(chat_flow.chat, "chat_endpoint") as delegated,
            patch.object(chat_flow, "save_chat_turn_metric"),
        ):
            result = chat_flow.chat_endpoint(
                self._request("a to w takim razie nie", draft)
            )

        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["event"])
        self.assertIn("duplikatu", result["message"])
        delegated.assert_not_called()

    def test_metric_records_latency_operation_and_status(self):
        delegated_result = {
            "status": "calendar_search",
            "message": "Brak wydarzeń.",
            "event": {"operation": "search", "search": {}, "matches": []},
        }
        request = self._request("jakie mam plany?")

        with (
            patch.object(chat_flow.chat, "chat_endpoint", return_value=delegated_result),
            patch.object(chat_flow, "perf_counter", side_effect=[10.0, 10.123]),
            patch.object(chat_flow, "save_chat_turn_metric") as save_metric,
        ):
            result = chat_flow.chat_endpoint(request)

        self.assertEqual(result, delegated_result)
        save_metric.assert_called_once_with(
            user_id="local-user",
            session_id="test-session",
            operation="search",
            status="calendar_search",
            latency_ms=123,
            clarification_required=False,
            had_draft=False,
            message_length=len("jakie mam plany?"),
        )

    def test_needs_input_metric_marks_clarification(self):
        delegated_result = {
            "status": "needs_input",
            "message": "Ile ma trwać wydarzenie?",
            "event": {"operation": "create"},
        }

        with (
            patch.object(chat_flow.chat, "chat_endpoint", return_value=delegated_result),
            patch.object(chat_flow, "save_chat_turn_metric") as save_metric,
        ):
            chat_flow.chat_endpoint(self._request("dodaj trening jutro o 17"))

        self.assertTrue(save_metric.call_args.kwargs["clarification_required"])
        self.assertEqual(save_metric.call_args.kwargs["operation"], "create")


if __name__ == "__main__":
    unittest.main()
