import unittest
from unittest.mock import Mock, patch

from app.services import google_calendar, llm_service, turn_timing


class ComponentTimingTests(unittest.TestCase):
    def test_context_accumulates_and_resets_component_timings(self):
        token = turn_timing.start_turn_timing()
        try:
            turn_timing.record_component("llm", 1200)
            turn_timing.record_component("llm", 300)
            turn_timing.record_component("calendar", 250)
            snapshot = turn_timing.snapshot_turn_timing()

            self.assertEqual(snapshot["llm_latency_ms"], 1500)
            self.assertEqual(snapshot["calendar_latency_ms"], 250)
            self.assertEqual(snapshot["llm_calls"], 2)
            self.assertEqual(snapshot["calendar_calls"], 1)
        finally:
            turn_timing.reset_turn_timing(token)

        self.assertEqual(
            turn_timing.snapshot_turn_timing(),
            {
                "llm_latency_ms": 0,
                "calendar_latency_ms": 0,
                "llm_calls": 0,
                "calendar_calls": 0,
            },
        )

    def test_llm_adapter_records_ollama_round_trip(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "message": {
                "content": '{"reply":"ok","status":"chat","operation":"chat"}'
            }
        }

        token = turn_timing.start_turn_timing()
        try:
            with (
                patch.object(llm_service, "find_learning_examples", return_value=[]),
                patch.object(llm_service.requests, "post", return_value=response),
                patch.object(llm_service, "perf_counter", side_effect=[10.0, 12.5]),
            ):
                result = llm_service.ask_llm("hej", [], user_id="local-user")

            snapshot = turn_timing.snapshot_turn_timing()
        finally:
            turn_timing.reset_turn_timing(token)

        self.assertEqual(result["operation"], "chat")
        self.assertEqual(snapshot["llm_latency_ms"], 2500)
        self.assertEqual(snapshot["llm_calls"], 1)
        self.assertEqual(snapshot["calendar_latency_ms"], 0)

    def test_calendar_execute_records_api_round_trip(self):
        request = Mock()
        request.execute.return_value = {"items": []}

        token = turn_timing.start_turn_timing()
        try:
            with patch.object(
                google_calendar,
                "perf_counter",
                side_effect=[20.0, 20.125],
            ):
                result = google_calendar._execute_calendar_request(request)

            snapshot = turn_timing.snapshot_turn_timing()
        finally:
            turn_timing.reset_turn_timing(token)

        self.assertEqual(result, {"items": []})
        self.assertEqual(snapshot["calendar_latency_ms"], 125)
        self.assertEqual(snapshot["calendar_calls"], 1)
        self.assertEqual(snapshot["llm_latency_ms"], 0)


if __name__ == "__main__":
    unittest.main()
