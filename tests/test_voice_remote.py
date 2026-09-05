import os
import unittest
from unittest.mock import Mock, patch

os.environ["SEHCS_VOICE_ENABLED"] = "true"
os.environ["SEHCS_VOICE_DEVICE_URL"] = "http://pi.local:5051"
os.environ["SEHCS_DEVICE_TOKEN"] = "test-token"

import voice


class RemoteVoiceTests(unittest.TestCase):
    def setUp(self):
        os.environ["SEHCS_DEVICE_TOKEN"] = "test-token"

    @patch("voice.requests.post")
    @patch("voice.subprocess.Popen")
    def test_speak_uses_pi_when_configured(self, local_process, post):
        response = Mock(status_code=202)
        post.return_value = response

        self.assertTrue(voice.speak("Medication reminder", enabled=True))
        post.assert_called_once_with(
            "http://pi.local:5051/speak",
            json={"message": "Medication reminder"},
            headers={"X-Voice-Token": "test-token"},
            timeout=3,
        )
        local_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()