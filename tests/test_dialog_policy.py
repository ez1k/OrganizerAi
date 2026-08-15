import unittest

from app.services.dialog_policy import apply_dialog_policy, infer_operation


class DialogPolicyTests(unittest.TestCase):
    def test_explicit_intent_overrides_are_high_confidence(self):
        cases = (
            ("dodaj trening jutro", "search", "create"),
            ("usuń dentystę jutro", "search", "delete"),
            ("co mam jutro w kalendarzu", "chat", "search"),
            ("jaka będzie jutro pogoda?", "chat", "external_search"),
            ("hej, co tam?", "search", "chat"),
        )
        for message, llm_operation, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(infer_operation(message, llm_operation), expected)

    def test_ambiguous_message_keeps_llm_operation(self):
        self.assertEqual(infer_operation("a ten drugi?", "delete"), "delete")

    def test_active_operation_can_be_cancelled(self):
        result = apply_dialog_policy(
            "w sumie nieważne, odpuśćmy to",
            {"operation": "create", "event": {"title": "nauka"}},
            current_state={"operation": "create", "title": "nauka"},
        )
        self.assertEqual(result["operation"], "cancelled")
        self.assertEqual(result["status"], "cancelled")

    def test_complete_create_is_ready_for_confirmation(self):
        result = apply_dialog_policy(
            "zaplanuj naukę jutro o 19 na 60 minut",
            {
                "operation": "create",
                "event": {
                    "title": "nauka",
                    "date_hint": "jutro",
                    "time_hint": "19:00",
                    "duration_minutes": 60,
                },
            },
        )
        self.assertEqual(result["status"], "ready_for_confirmation")

    def test_incomplete_create_needs_input_even_if_model_claims_ready(self):
        result = apply_dialog_policy(
            "dodaj spotkanie jutro o 18",
            {
                "operation": "create",
                "status": "ready_for_confirmation",
                "event": {
                    "title": "spotkanie",
                    "date_hint": "jutro",
                    "time_hint": "18:00",
                },
            },
        )
        self.assertEqual(result["status"], "needs_input")

    def test_create_correction_uses_existing_state_for_completeness(self):
        state = {
            "operation": "create",
            "title": "trening",
            "date_hint": "jutro",
            "time_hint": "17:00",
            "duration_minutes": 90,
        }
        result = apply_dialog_policy(
            "jednak o 18:30",
            {"operation": "create", "event": {"time_hint": "18:30"}},
            current_state=state,
        )
        self.assertEqual(result["status"], "ready_for_confirmation")

    def test_vague_time_is_removed_and_create_needs_input(self):
        result = apply_dialog_policy(
            "jutro wieczorem chcę pouczyć się przez godzinę",
            {
                "operation": "create",
                "event": {
                    "title": "nauka",
                    "date_hint": "jutro",
                    "time_hint": "wieczorem",
                    "duration_minutes": 60,
                },
            },
        )
        self.assertNotIn("time_hint", result["event"])
        self.assertEqual(result["status"], "needs_input")

    def test_weekday_inflection_is_canonicalized(self):
        result = apply_dialog_policy(
            "wrzuć mi na sobotę trening",
            {"operation": "create", "event": {"date_hint": "sobotę"}},
        )
        self.assertEqual(result["event"]["date_hint"], "sobota")

    def test_search_status_is_always_calendar_search(self):
        result = apply_dialog_policy(
            "sprawdź co mam jutro",
            {"operation": "search", "status": "needs_input", "search": {"date_hint": "jutro"}},
        )
        self.assertEqual(result["operation"], "search")
        self.assertEqual(result["status"], "calendar_search")

    def test_delete_without_target_needs_input(self):
        result = apply_dialog_policy(
            "usuń mi to wydarzenie",
            {"operation": "delete", "status": "calendar_delete_confirmation"},
        )
        self.assertEqual(result["operation"], "delete")
        self.assertEqual(result["status"], "needs_input")

    def test_delete_with_search_criteria_can_request_confirmation(self):
        result = apply_dialog_policy(
            "wywal trening z poniedziałku",
            {
                "operation": "delete",
                "search": {"title": "trening", "date_hint": "poniedziałek"},
            },
        )
        self.assertEqual(result["status"], "calendar_delete_confirmation")

    def test_delete_anaphora_can_use_existing_matches(self):
        result = apply_dialog_policy(
            "usuń ten drugi",
            {"operation": "delete"},
            current_state={
                "operation": "delete",
                "matches": [{"id": "1"}, {"id": "2"}],
            },
        )
        self.assertEqual(result["status"], "calendar_delete_confirmation")

    def test_external_and_chat_statuses_are_policy_owned(self):
        external = apply_dialog_policy(
            "jaka będzie pogoda?",
            {"operation": "chat", "status": "needs_input"},
        )
        chat = apply_dialog_policy(
            "hej, co tam?",
            {"operation": "search", "status": "calendar_search"},
        )
        self.assertEqual((external["operation"], external["status"]), ("external_search", "external_search"))
        self.assertEqual((chat["operation"], chat["status"]), ("chat", "chat"))


if __name__ == "__main__":
    unittest.main()
