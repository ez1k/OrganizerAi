import json
import unittest
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

    def test_static_few_shots_cover_observed_baseline_error_classes(self):
        joined = "\n".join(item["content"] for item in llm_service.STATIC_FEW_SHOT_MESSAGES)
        for fragment in (
            "dwie godziny nauki",
            "90 minut",
            "jutro wieczorem",
            "godzinę czytania o 20",
            "czy mam jutro coś z dentystą",
            "wywal mi trening",
            "w kinie",
            "hej, co tam",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, joined)

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
