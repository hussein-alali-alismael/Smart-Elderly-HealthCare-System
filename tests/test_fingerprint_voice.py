import os
import unittest
from unittest.mock import Mock, patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

from pi_client import fingerprint_client
from pi_client.fingerprint_sensor_bridge import _local_result


class FingerprintVoiceTests(unittest.TestCase):
    @patch("pi_client.fingerprint_client.speak_message")
    @patch("pi_client.fingerprint_client.requests.post")
    def test_speaks_success_message(self, post, speak):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"message": "Medication recorded."}
        post.return_value = response

        result = fingerprint_client.send_payload("http://server", {"resident_id": 7})

        self.assertTrue(result["ok"])
        self.assertEqual(speak.call_args.args[0], "Medication recorded.")

    @patch("pi_client.fingerprint_client.speak_message")
    @patch("pi_client.fingerprint_client.requests.post")
    def test_speaks_server_error_message(self, post, speak):
        response = Mock(ok=False, status_code=401)
        response.json.return_value = {"error": "Fingerprint device authentication required."}
        post.return_value = response

        fingerprint_client.send_payload("http://server", {"resident_id": 7})

        self.assertEqual(
            speak.call_args.args[0], "Fingerprint device authentication required."
        )

    @patch("pi_client.fingerprint_client.speak_message")
    @patch("pi_client.fingerprint_client.requests.post", side_effect=fingerprint_client.requests.RequestException("offline"))
    def test_speaks_final_network_error(self, post, speak):
        fingerprint_client.send_payload("http://server", {"resident_id": 7}, retries=1)

        self.assertEqual(speak.call_args.args[0], "offline")

    @patch("pi_client.fingerprint_sensor_bridge.speak_message")
    def test_speaks_local_wrong_fingerprint_error(self, speak_message):
        message = "AS608 did not recognize this finger. Enroll it again or check the sensor memory."
        result = _local_result(message, True)

        self.assertFalse(result["ok"])
        speak_message.assert_called_once_with(message, enabled=True)


if __name__ == "__main__":
    unittest.main()
