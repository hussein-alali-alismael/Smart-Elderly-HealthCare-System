import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_agent import MedicationSchedulerAgent, ScheduleRecord


class FakeCursor:
    def __init__(self, existing):
        self.existing = existing
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        self.executions.append((query, params))

    def fetchone(self):
        return self.existing


class FakeConnection:
    def __init__(self, existing):
        self.cursor_instance = FakeCursor(existing)

    def cursor(self):
        return self.cursor_instance


def schedule(time_of_day="08:00:00"):
    return ScheduleRecord(
        schedule_id=1,
        resident_id=7,
        resident_name="Ahmed",
        medication_id=1,
        medication_name="Metformin",
        frequency="daily",
        start_date="2026-01-01",
        end_date=None,
        schedule_time_id=3,
        time_of_day=time_of_day,
    )


class IntakeStatusTests(unittest.TestCase):
    @patch("ai_agent.get_db_connection")
    def test_new_daily_intake_starts_pending(self, get_connection):
        connection = FakeConnection(None)
        get_connection.return_value = connection

        MedicationSchedulerAgent().node_3_sync_daily_intake_statuses(
            [schedule()], now=datetime(2026, 8, 28, 7, 30)
        )

        insert = connection.cursor_instance.executions[-1]
        self.assertIn("INSERT INTO medication_intakes", insert[0])
        self.assertEqual(insert[1], (3, "2026-08-28 08:00:00", "pending"))

    @patch("ai_agent.get_db_connection")
    def test_expired_pending_intake_becomes_missed(self, get_connection):
        connection = FakeConnection({"id": 42, "status": "pending"})
        get_connection.return_value = connection

        MedicationSchedulerAgent(announcement_window_minutes=10).node_3_sync_daily_intake_statuses(
            [schedule()], now=datetime(2026, 8, 28, 8, 20)
        )

        update = connection.cursor_instance.executions[-1]
        self.assertIn("UPDATE medication_intakes", update[0])
        self.assertEqual(update[1], ("missed", 42))

    @patch("ai_agent.get_db_connection")
    def test_new_expired_intake_starts_missed(self, get_connection):
        connection = FakeConnection(None)
        get_connection.return_value = connection

        MedicationSchedulerAgent(announcement_window_minutes=10).node_3_sync_daily_intake_statuses(
            [schedule()], now=datetime(2026, 8, 28, 8, 20)
        )

        insert = connection.cursor_instance.executions[-1]
        self.assertEqual(insert[1], (3, "2026-08-28 08:00:00", "missed"))

    @patch("ai_agent.get_db_connection")
    def test_taken_intake_is_not_overwritten(self, get_connection):
        connection = FakeConnection({"id": 42, "status": "taken"})
        get_connection.return_value = connection

        MedicationSchedulerAgent().node_3_sync_daily_intake_statuses(
            [schedule()], now=datetime(2026, 8, 28, 8, 20)
        )

        self.assertEqual(len(connection.cursor_instance.executions), 1)


if __name__ == "__main__":
    unittest.main()
