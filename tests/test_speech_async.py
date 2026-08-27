import os
import sys
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ai_agent


class AsyncSpeechTests(unittest.TestCase):
    def test_medication_assistant_is_optional_without_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            assistant = ai_agent.MedicationAssistant()

            self.assertIsNone(assistant._chain)
            self.assertIn("GEMINI_API_KEY", assistant.ask("Hello"))

    def test_medication_assistant_builds_chain_lazily(self):
        chain = MagicMock()
        chain.invoke.return_value.content = "Chat response"
        with patch.object(ai_agent.MedicationAssistant, "_build_chain", return_value=chain) as build_chain:
            assistant = ai_agent.MedicationAssistant(api_key="test-key")

            build_chain.assert_not_called()
            self.assertEqual(assistant.ask("Hello"), "Chat response")
            build_chain.assert_called_once_with()

    @patch("ai_agent.speak")
    def test_chat_answer_is_not_spoken(self, speak_mock):
        assistant = ai_agent.MedicationAssistant.__new__(ai_agent.MedicationAssistant)
        assistant.api_key = "test-key"
        assistant._chain = MagicMock()
        assistant._chain.invoke.return_value.content = "Chat response"

        answer = assistant.ask("Hello")

        self.assertEqual(answer, "Chat response")
        speak_mock.assert_not_called()

    @patch("ai_agent.threading.Thread")
    def test_scheduler_speech_starts_daemon_thread(self, thread_class):
        ai_agent._speak_async("Medication reminder")

        thread_class.assert_called_once()
        self.assertTrue(thread_class.call_args.kwargs["daemon"])
        thread_class.return_value.start.assert_called_once_with()

    @patch("ai_agent.speak", side_effect=RuntimeError("stuck TTS"))
    @patch("ai_agent.server_voice_enabled", return_value=True)
    @patch("ai_agent.threading.Thread")
    def test_tts_failure_is_contained_in_worker_target(
        self, thread_class, voice_enabled_mock, speak_mock
    ):
        ai_agent._speak_async("Medication reminder")
        target = thread_class.call_args.kwargs["target"]

        target()

        speak_mock.assert_called_once_with("Medication reminder", enabled=True)
        voice_enabled_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
