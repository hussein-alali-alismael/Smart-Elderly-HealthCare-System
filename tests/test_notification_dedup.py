import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_agent import MedicationSchedulerAgent


class FakeCursor:
    def __init__(self, existing_dates):
        self.existing_dates = set(existing_dates)
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        self.params = params

    def fetchone(self):
        return {"id": 1} if self.params[-1] in self.existing_dates else None


class FakeConnection:
    def __init__(self, existing_dates):
        self.cursor_instance = FakeCursor(existing_dates)

    def cursor(self):
        return self.cursor_instance


class NotificationDeduplicationTests(unittest.TestCase):
    def test_notification_is_deduplicated_only_for_the_same_day(self):
        connection = FakeConnection({"2026-08-27"})
        agent = MedicationSchedulerAgent()

        self.assertFalse(
            agent._notification_exists(
                connection,
                1,
                "medication_reminder",
                "Reminder",
                notification_date="2026-08-28",
            )
        )
        self.assertTrue(
            agent._notification_exists(
                connection,
                1,
                "medication_reminder",
                "Reminder",
                notification_date="2026-08-27",
            )
        )
        self.assertEqual(connection.cursor_instance.params[-1], "2026-08-27")


if __name__ == "__main__":
    unittest.main()
