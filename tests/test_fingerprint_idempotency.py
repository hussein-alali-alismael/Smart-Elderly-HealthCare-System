import os
import sys
import unittest
from datetime import date, datetime
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fingerprint_agent import (
    FingerprintMedicationAgent,
    FingerprintResident,
    MedicationScheduleRow,
)


class FakeCursor:
    def __init__(self, existing):
        self.existing = existing
        self.executions = []
        self.lastrowid = 99

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

    def commit(self):
        pass


class FingerprintIdempotencyTests(unittest.TestCase):
    def test_near_midnight_schedule_uses_previous_date(self):
        agent = FingerprintMedicationAgent(announcement_window_minutes=10)
        now = datetime(2026, 8, 29, 0, 3, 0)

        planned = agent._planned_datetime_for_today(now, "23:55:00")

        self.assertEqual(planned, datetime(2026, 8, 28, 23, 55, 0))
        self.assertIsNotNone(agent.node_5_choose_nearest_medication_time([
            MedicationScheduleRow(
                schedule_id=1,
                resident_id=7,
                resident_name="Ahmed",
                medication_id=1,
                medication_name="Metformin",
                medication_dosage="500mg",
                schedule_time_id=3,
                time_of_day="23:55:00",
                start_date=date(2026, 1, 1),
                end_date=None,
                is_active=1,
            )
        ], now=now))

    @patch("fingerprint_agent.get_db_connection")
    def test_second_scan_preserves_first_taken_time(self, get_connection):
        connection = FakeConnection({
            "id": 42,
            "status": "taken",
            "actualIntakeDateTime": datetime(2026, 8, 28, 8, 2, 0),
        })
        get_connection.return_value = connection
        agent = FingerprintMedicationAgent()
        resident = FingerprintResident(id=7, name="Ahmed", fingerprintTemplate=b"template")
        schedule = MedicationScheduleRow(
            schedule_id=1,
            resident_id=7,
            resident_name="Ahmed",
            medication_id=1,
            medication_name="Metformin",
            medication_dosage="500mg",
            schedule_time_id=3,
            time_of_day="08:00:00",
            start_date=date(2026, 1, 1),
            end_date=None,
            is_active=1,
        )

        result = agent.final_node_upsert_intake_log(
            resident,
            schedule,
            now=datetime(2026, 8, 28, 8, 7, 0),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.intake_row_id, 42)
        self.assertEqual(result.actual_intake_datetime, "2026-08-28 08:02:00")
        self.assertEqual(len(connection.cursor_instance.executions), 1)
        self.assertIn("SELECT id, status, actualIntakeDateTime", connection.cursor_instance.executions[0][0])
        self.assertNotIn("UPDATE medication_intakes", connection.cursor_instance.executions[0][0])


if __name__ == "__main__":
    unittest.main()
