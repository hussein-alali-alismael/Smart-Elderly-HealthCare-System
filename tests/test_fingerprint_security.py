import os
import sys
import unittest
from unittest.mock import patch

os.environ["FINGERPRINT_DEVICE_TOKEN"] = "test-device-token"
os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app
from fingerprint_agent import FingerprintMedicationAgent


class FingerprintSecurityTests(unittest.TestCase):
    def test_checkin_requires_device_token(self):
        client = flask_app.test_client()

        response = client.post(
            "/api/fingerprint-checkin",
            json={"fingerprint_id": 7},
        )

        self.assertEqual(response.status_code, 401)

    def test_resident_id_alone_never_queries_or_matches_resident(self):
        agent = FingerprintMedicationAgent()
        with patch("fingerprint_agent.get_db_connection") as get_connection:
            resident = agent.node_1_find_resident_by_fingerprint({"fingerprint_id": 7})

        self.assertIsNone(resident)
        get_connection.assert_not_called()

    def test_numeric_fingerprint_input_is_not_trusted(self):
        agent = FingerprintMedicationAgent()
        with patch("fingerprint_agent.get_db_connection") as get_connection:
            resident = agent.node_1_find_resident_by_fingerprint(7)

        self.assertIsNone(resident)
        get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
