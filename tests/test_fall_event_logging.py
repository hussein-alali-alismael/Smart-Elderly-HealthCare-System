import os
import sys
import unittest
from unittest.mock import patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fall_alert_agent import FallDetectionPipeline


class FakeCursor:
    def __init__(self):
        self.executions = []
        self.lastrowid = 17

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        self.executions.append((query, params))


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass


class FallEventLoggingTests(unittest.TestCase):
    @patch("fall_alert_agent.get_db_connection")
    def test_noncritical_event_is_persisted_without_emergency_notification(self, get_connection):
        connection = FakeConnection()
        get_connection.return_value = connection
        pipeline = FallDetectionPipeline(backend_url="")

        result = pipeline.process_fall_event({
            "resident_id": 7,
            "gravity_level": "MOVEMENT",
            "detected_at": "2026-08-28T10:00:00",
        })

        self.assertEqual(result["status"], "logged")
        self.assertTrue(result["db_synced"])
        self.assertEqual(len(connection.cursor_instance.executions), 1)
        self.assertIn("INSERT INTO fall_incidents", connection.cursor_instance.executions[0][0])
        self.assertNotIn("INSERT INTO notifications", connection.cursor_instance.executions[0][0])
        self.assertEqual(connection.cursor_instance.executions[0][1][5], "detected")


if __name__ == "__main__":
    unittest.main()
