import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services import llm_service


class LlmSemanticV3Tests(unittest.TestCase):
    def test_prompt_assigns_status_policy_to_backend(self):
        prompt = llm_service.SYSTEM_PROMPT
        self.assertIn("WYŁĄCZNIE rozpoznać znaczenie wiadomości i wyodrębnić dane", prompt)
        self.assertIn("NIE decydujesz o stanie dialogu", prompt)
        self.assertIn("status wylicza backend", prompt)
        self.assertNotIn('"status": "needs_input', prompt)

    def test_prompt_keeps_semantic_intents_and_slot_safety(self):
        prompt = llm_service.SYSTEM_PROMPT
        for fragment in (
            "- create:",
            "- search:",
            "- delete:",
            "- external_search:",
            "- chat:",
            "- cancelled:",
            "„półtorej godziny”=90",
            "„dwie godziny”=120",
            "nie dodawaj „dziś”",
            "nie są dokładną godziną",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prompt)

    def test_prompt_allows_general_chat_without_web_lookup(self):
        prompt = llm_service.SYSTEM_PROMPT
        self.assertIn('Dla operation="chat" odpowiedz', prompt)
        self.assertIn('„ile to 4x4?”', prompt)
        self.assertIn('operation="external_search" wybieraj tylko wtedy', prompt)

    def test_v3_few_shots_are_semantic_and_do_not_contain_status(self):
        messages = llm_service.STATIC_FEW_SHOT_MESSAGES
        self.assertEqual(len(messages), 6)
        assistant_messages = [item for item in messages if item["role"] == "assistant"]
        self.assertEqual(len(assistant_messages), 3)
        for item in assistant_messages:
            with self.subTest(content=item["content"]):
                parsed = json.loads(item["content"])
                self.assertIn("operation", parsed)
                self.assertNotIn("status", parsed)

    def test_static_few_shots_do_not_copy_frozen_nlp_dataset_messages(self):
        project_root = Path(__file__).resolve().parents[1]
        dataset = json.loads(
            (project_root / "benchmarks" / "nlp_quality_v1.json").read_text(encoding="utf-8")
        )
        static_user_messages = {
            item["content"]
            for item in llm_service.STATIC_FEW_SHOT_MESSAGES
            if item["role"] == "user"
        }
        frozen_messages = {case["message"] for case in dataset}
        self.assertFalse(static_user_messages & frozen_messages)

    def test_semantic_adapter_does_not_require_model_status(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "message": {
                "content": json.dumps(
                    {"reply": "ok", "operation": "chat"},
                    ensure_ascii=False,
                )
            }
        }

        with (
            patch.object(llm_service, "find_learning_examples", return_value=[]),
            patch.object(llm_service.requests, "post", return_value=response),
        ):
            result = llm_service.ask_llm_semantic("hej", [], user_id="local-user")

        self.assertEqual(result["operation"], "chat")
        self.assertNotIn("status", result)

    def test_runtime_adapter_applies_deterministic_policy(self):
        with patch.object(
            llm_service,
            "ask_llm_semantic",
            return_value={
                "reply": "ok",
                "operation": "create",
                "event": {
                    "title": "nauka",
                    "date_hint": "jutro",
                    "time_hint": "18:00",
                },
            },
        ):
            result = llm_service.ask_llm("dodaj naukę jutro o 18", [], user_id="local-user")

        self.assertEqual(result["operation"], "create")
        self.assertEqual(result["status"], "needs_input")

    def test_runtime_delete_without_target_uses_non_calendar_route(self):
        with patch.object(
            llm_service,
            "ask_llm_semantic",
            return_value={"reply": "ok", "operation": "delete"},
        ):
            result = llm_service.ask_llm("usuń mi to wydarzenie", [], user_id="local-user")

        self.assertEqual(result["semantic_operation"], "delete")
        self.assertEqual(result["operation"], "__needs_input__")
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("Które wydarzenie", result["reply"])


if __name__ == "__main__":
    unittest.main()
