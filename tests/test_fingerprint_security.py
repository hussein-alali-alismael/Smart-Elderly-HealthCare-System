import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ["SEHCS_DEVICE_TOKEN"] = "test-device-token"
os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app
from fingerprint_agent import FingerprintMedicationAgent


class FingerprintSecurityTests(unittest.TestCase):
    def setUp(self):
        os.environ["SEHCS_DEVICE_TOKEN"] = "test-device-token"

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

    def test_authenticated_sensor_position_is_normalized_to_resident_id(self):
        client = flask_app.test_client()
        mock_agent = MagicMock()
        mock_agent.process_fingerprint.return_value = {
            "success": True,
            "step": "final",
            "message": "Resident matched.",
            "resident": {"id": 7, "name": "Ahmed"},
            "result": {"status": "taken"},
        }

        with patch("app.FingerprintMedicationAgent", return_value=mock_agent):
            response = client.post(
                "/api/fingerprint-checkin",
                json={"fingerprint_id": 7, "sensor_position": 7, "accuracy": 310},
                headers={"X-Fingerprint-Token": "test-device-token"},
            )

        self.assertEqual(response.status_code, 200)
        mock_agent.process_fingerprint.assert_called_once_with({"resident_id": 7, "sensor_position": 7, "accuracy": 310})

    def test_device_token_allows_fingerprint_enrollment_without_session(self):
        client = flask_app.test_client()
        with patch("app.set_resident_fingerprint", return_value=("ok", 200)) as set_fp:
            response = client.post(
                "/api/residents/11/fingerprint",
                json={"fingerprintTemplate": "Zm9v"},
                headers={"X-Fingerprint-Token": "test-device-token"},
            )

        self.assertEqual(response.status_code, 200)
        set_fp.assert_called_once_with(11, "Zm9v", None, sensor_position=None)

    def test_sensor_slot_mapping_matches_db_resident(self):
        agent = FingerprintMedicationAgent()
        connection = MagicMock()
        cursor = MagicMock()
        row = {"id": 11, "name": "Ali Hassan", "fingerprintTemplate": b"template"}
        cursor.fetchone.return_value = row
        connection.cursor.return_value.__enter__.return_value = cursor

        with patch("fingerprint_agent.get_db_connection", return_value=connection):
            resident = agent.node_1_find_resident_by_fingerprint({"sensor_position": 11})

        self.assertIsNotNone(resident)
        self.assertEqual(resident.id, 11)
        self.assertEqual(resident.name, "Ali Hassan")

    def test_sensor_slot_precedes_template_match_for_as608_scan(self):
        agent = FingerprintMedicationAgent()
        connection = MagicMock()
        cursor = MagicMock()
        row = {"id": 11, "name": "Ali Hassan", "fingerprintTemplate": b"stored-template"}
        cursor.fetchone.return_value = row
        connection.cursor.return_value.__enter__.return_value = cursor

        with patch("fingerprint_agent.get_db_connection", return_value=connection):
            resident = agent.node_1_find_resident_by_fingerprint({
                "sensor_position": 11,
                "fingerprintTemplate": b"different-template-each-scan",
            })

        self.assertIsNotNone(resident)
        self.assertEqual(resident.id, 11)


if __name__ == "__main__":
    unittest.main()
