import json
import unittest
from unittest.mock import Mock, patch

from app.routes import reflections
from app.schemas import ReflectionAnalysisRequest
from app.services.reflection_nlp_service import (
    analyze_event_reflection,
    sanitize_reflection_analysis,
)


class ReflectionNlpTests(unittest.TestCase):
    def test_explicit_rating_overrides_model_estimate(self):
        result = sanitize_reflection_analysis(
            "Było świetnie, daję 5/5.",
            {
                "sentiment": "positive",
                "rating": 3,
                "worth_repeating": True,
                "confidence": "high",
                "summary": "Bardzo pozytywne doświadczenie.",
            },
        )
        self.assertEqual(result["rating"], 5)
        self.assertEqual(result["sentiment"], "positive")

    def test_invalid_sentiment_is_rejected(self):
        with self.assertRaises(ValueError):
            sanitize_reflection_analysis(
                "Było okej.",
                {
                    "sentiment": "happy",
                    "rating": 3,
                    "worth_repeating": None,
                    "confidence": "medium",
                    "summary": "Neutralnie.",
                },
            )

    def test_invalid_optional_fields_are_safely_dropped(self):
        result = sanitize_reflection_analysis(
            "Trudno powiedzieć.",
            {
                "sentiment": "mixed",
                "rating": 9,
                "worth_repeating": "yes",
                "confidence": "unknown",
                "summary": "  mieszane odczucia  ",
            },
        )
        self.assertIsNone(result["rating"])
        self.assertIsNone(result["worth_repeating"])
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["summary"], "mieszane odczucia")

    def test_analyze_event_reflection_calls_local_mistral_once(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "message": {
                "content": json.dumps(
                    {
                        "sentiment": "positive",
                        "rating": 5,
                        "worth_repeating": True,
                        "confidence": "high",
                        "summary": "Aktywność została oceniona bardzo pozytywnie.",
                    },
                    ensure_ascii=False,
                )
            }
        }

        with (
            patch("app.services.reflection_nlp_service.requests.post", return_value=response) as post,
            patch("app.services.reflection_nlp_service.perf_counter", side_effect=[10.0, 12.345]),
        ):
            result = analyze_event_reflection("Było super, naprawdę dobrze mi zrobiło.")

        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["rating"], 5)
        self.assertTrue(result["worth_repeating"])
        self.assertEqual(result["llm_latency_ms"], 2345)
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "mistral")
        self.assertEqual(payload["format"], "json")

    def test_analysis_endpoint_does_not_persist_or_schedule(self):
        analysis = {
            "sentiment": "positive",
            "rating": 4,
            "worth_repeating": True,
            "confidence": "high",
            "summary": "Pozytywna ocena.",
            "llm_latency_ms": 100,
        }
        request = ReflectionAnalysisRequest(feedback_text="Było bardzo fajnie.")

        with (
            patch.object(reflections, "analyze_event_reflection", return_value=analysis),
            patch.object(reflections, "save_event_reflection") as save_reflection,
            patch.object(reflections, "schedule_motivation_reminder") as schedule_reminder,
        ):
            result = reflections.analyze_reflection(request)

        self.assertEqual(result, {"status": "analyzed", "analysis": analysis})
        save_reflection.assert_not_called()
        schedule_reminder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
