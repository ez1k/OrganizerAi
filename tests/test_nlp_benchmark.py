import unittest

from scripts import benchmark_nlp


class NlpBenchmarkScoringTests(unittest.TestCase):
    def test_normalization_is_case_and_accent_insensitive(self):
        self.assertEqual(benchmark_nlp._normalize("  SIŁOWNIĘ "), "silownie")

    def test_time_comparison_accepts_hour_without_minutes(self):
        self.assertTrue(benchmark_nlp._equal("time_hint", "18:00", "18"))
        self.assertTrue(benchmark_nlp._equal("time_hint", "18:00", "o 18"))

    def test_missing_slot_is_counted_as_hallucination_check(self):
        case = {
            "expected": {
                "operation": "create",
                "status": "needs_input",
                "event": {
                    "equals": {"date_hint": "jutro"},
                    "missing": ["time_hint"],
                },
            }
        }
        result = {
            "operation": "create",
            "status": "needs_input",
            "event": {"date_hint": "jutro", "time_hint": None},
        }

        validation = benchmark_nlp._validate_case(case, result)

        self.assertTrue(validation["passed"])
        self.assertEqual(validation["slot_total"], 1)
        self.assertEqual(validation["slot_correct"], 1)
        self.assertEqual(validation["hallucination_total"], 1)
        self.assertEqual(validation["hallucination_correct"], 1)

    def test_invented_missing_slot_fails_case(self):
        case = {
            "expected": {
                "operation": "create",
                "status": "needs_input",
                "event": {"missing": ["time_hint"]},
            }
        }
        result = {
            "operation": "create",
            "status": "needs_input",
            "event": {"time_hint": "18:00"},
        }

        validation = benchmark_nlp._validate_case(case, result)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["hallucination_correct"], 0)
        self.assertTrue(any("should be missing" in error for error in validation["errors"]))

    def test_delete_event_id_is_forbidden_anywhere(self):
        case = {
            "expected": {
                "operation": "delete",
                "status": "calendar_delete_confirmation",
            },
            "forbidden_keys_anywhere": ["event_id"],
        }
        result = {
            "operation": "delete",
            "status": "calendar_delete_confirmation",
            "search": {"event_id": "hallucinated-id"},
        }

        validation = benchmark_nlp._validate_case(case, result)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["hallucination_total"], 1)
        self.assertEqual(validation["hallucination_correct"], 0)

    def test_semantic_title_fragment_is_flexible(self):
        case = {
            "expected": {
                "operation": "create",
                "status": "ready_for_confirmation",
                "event": {"contains": {"title": ["silown"]}},
            }
        }
        result = {
            "operation": "create",
            "status": "ready_for_confirmation",
            "event": {"title": "Siłownię"},
        }

        validation = benchmark_nlp._validate_case(case, result)
        self.assertTrue(validation["passed"])


if __name__ == "__main__":
    unittest.main()
