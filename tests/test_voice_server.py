import os
import sys
import unittest
from unittest.mock import patch

os.environ["SEHCS_DEVICE_TOKEN"] = "test-voice-token"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pi_client.voice_server import process_speech_request


class VoiceServerTests(unittest.TestCase):
    def setUp(self):
        pass

    @patch.dict(os.environ, {"SEHCS_DEVICE_TOKEN": "test-voice-token"})
    def test_requires_voice_token(self):
        status, _ = process_speech_request("", {"message": "hello"})
        self.assertEqual(status, 401)

    @patch.dict(os.environ, {"SEHCS_DEVICE_TOKEN": "test-voice-token"})
    @patch("pi_client.voice_server.threading.Thread")
    def test_speaks_authenticated_message(self, thread_class):
        status, _ = process_speech_request("test-voice-token", {"message": "Medication reminder"})
        self.assertEqual(status, 202)
        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once_with()
        thread_class.call_args.kwargs["target"]()

    @patch.dict(os.environ, {"SEHCS_DEVICE_TOKEN": "test-voice-token"})
    @patch("pi_client.voice_server.threading.Thread")
    def test_accepts_message_without_blocking_on_speech(self, thread_class):
        status, _ = process_speech_request("test-voice-token", {"message": "Voice test"})
        self.assertEqual(status, 202)
        thread_class.assert_called_once()


if __name__ == "__main__":
    unittest.main()
