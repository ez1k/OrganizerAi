import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services import llm_service


class LlmPromptV2Tests(unittest.TestCase):
    def test_prompt_defines_natural_duration_values(self):
        prompt = llm_service.SYSTEM_PROMPT
        for fragment in (
            '"pół godziny"=30',
            '"godzinę"/"jedną godzinę"=60',
            '"półtorej godziny"=90',
            '"dwie godziny"=120',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prompt)

    def test_prompt_forbids_invented_today_and_vague_clock_time(self):
        prompt = llm_service.SYSTEM_PROMPT
        self.assertIn('Nigdy nie zakładaj domyślnie "dzisiaj"', prompt)
        self.assertIn('"wieczorem"', prompt)
        self.assertIn("NIE są konkretną godziną", prompt)
        self.assertIn("status ma być needs_input", prompt)

    def test_prompt_defines_status_contract(self):
        prompt = llm_service.SYSTEM_PROMPT
        self.assertIn("create + kompletne 4 sloty -> ready_for_confirmation", prompt)
        self.assertIn("create + brak co najmniej jednego z 4 slotów -> needs_input", prompt)
        self.assertIn("search -> calendar_search", prompt)
        self.assertIn("delete bez wystarczających kryteriów -> needs_input", prompt)
        self.assertIn("cancelled -> cancelled", prompt)

    def test_static_few_shots_cover_observed_error_classes_with_paraphrases(self):
        joined = "\n".join(item["content"] for item in llm_service.STATIC_FEW_SHOT_MESSAGES)
        for fragment in (
            "dwie godziny pisania pracy",
            "90 minut",
            "jutro wieczorem",
            "godzinę medytacji o 21",
            "wizytę u lekarza",
            "skasuj mi zebranie",
            "w telewizji",
            "jak leci",
            "anuluj to",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, joined)

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

    def test_ask_llm_sends_static_few_shots_before_current_message(self):
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
