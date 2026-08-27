import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_agent import MedicationSchedulerAgent


class FakeCursor:
    def __init__(self):
        self.query = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance


class ScheduleValidityTests(unittest.TestCase):
    @patch("ai_agent.get_db_connection")
    def test_schedule_loader_filters_to_current_date(self, get_connection):
        connection = FakeConnection()
        get_connection.return_value = connection

        schedules = MedicationSchedulerAgent().node_1_load_schedule_time()
        today = datetime.now().date().isoformat()

        self.assertEqual(schedules, [])
        self.assertEqual(connection.cursor_instance.params, (today, today))
        self.assertIn("ms.startDate <= %s", connection.cursor_instance.query)
        self.assertIn("ms.endDate IS NULL OR ms.endDate >= %s", connection.cursor_instance.query)
        self.assertIn("ms.isActive = 1", connection.cursor_instance.query)


if __name__ == "__main__":
    unittest.main()
