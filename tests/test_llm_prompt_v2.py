import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services import llm_service


class LlmPromptV21Tests(unittest.TestCase):
    def test_prompt_keeps_intent_contract_explicit(self):
        prompt = llm_service.SYSTEM_PROMPT
        for fragment in (
            "- create: dodaj, zaplanuj, umów",
            "- search: sprawdź, pokaż, co mam",
            "- delete: usuń, skasuj, wywal",
            "- external_search: pytanie o pogodę, kino, film",
            "- chat: zwykła rozmowa/small-talk",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prompt)

    def test_prompt_defines_hard_slot_safety_rules(self):
        prompt = llm_service.SYSTEM_PROMPT
        for fragment in (
            "Nigdy nie zakładaj domyślnie „dzisiaj”",
            "„półtorej godziny”=90",
            "„dwie godziny”=120",
            'time_hint="12:00" i duration_minutes=90',
            "„rano”, „po południu”, „wieczorem” nie są dokładną godziną",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prompt)

    def test_prompt_has_short_pre_return_self_check(self):
        prompt = llm_service.SYSTEM_PROMPT
        self.assertIn("PRZED ZWRÓCENIEM JSON SPRAWDŹ:", prompt)
        self.assertIn("Czy operation odpowiada czasownikowi", prompt)
        self.assertIn("Czy każdy zwrócony slot pochodzi", prompt)
        self.assertIn("Tak -> ready_for_confirmation, nie -> needs_input", prompt)
        self.assertIn("Czy zawsze zwróciłeś operation i status?", prompt)
        self.assertIn("wyłącznie poprawny JSON", prompt)

    def test_v21_uses_exactly_three_few_shot_pairs(self):
        messages = llm_service.STATIC_FEW_SHOT_MESSAGES
        self.assertEqual(len(messages), 6)
        self.assertEqual([item["role"] for item in messages], [
            "user", "assistant", "user", "assistant", "user", "assistant"
        ])

        joined = "\n".join(item["content"] for item in messages)
        self.assertIn("półtorej godziny pisania pracy", joined)
        self.assertIn("jutro wieczorem", joined)
        self.assertIn("godzinę medytacji o 21", joined)

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

    def test_ask_llm_sends_minimal_few_shots_before_current_message(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "message": {
                "content": json.dumps(
                    {"reply": "ok", "status": "chat", "operation": "chat"},
                    ensure_ascii=False,
                )
            }
        }

        with (
            patch.object(llm_service, "find_learning_examples", return_value=[]),
            patch.object(llm_service.requests, "post", return_value=response) as post_mock,
        ):
            llm_service.ask_llm("hej", [], user_id="local-user")

        messages = post_mock.call_args.kwargs["json"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(
            messages[1 : 1 + len(llm_service.STATIC_FEW_SHOT_MESSAGES)],
            llm_service.STATIC_FEW_SHOT_MESSAGES,
        )
        self.assertIn("NOWA WIADOMOŚĆ UŻYTKOWNIKA:\nhej", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
