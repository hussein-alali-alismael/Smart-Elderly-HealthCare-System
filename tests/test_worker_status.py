import os
import sys
import unittest
from unittest.mock import patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module


class WorkerStatusTests(unittest.TestCase):
    def setUp(self):
        self.original_state = dict(app_module._notification_worker_state)
        self.original_thread = app_module._notification_worker_thread

    def tearDown(self):
        app_module._notification_worker_state.clear()
        app_module._notification_worker_state.update(self.original_state)
        app_module._notification_worker_thread = self.original_thread

    def test_dead_worker_is_reported_as_not_running(self):
        app_module._notification_worker_state["running"] = True
        with patch.object(app_module, "_notification_worker_thread") as thread:
            thread.is_alive.return_value = False
            with app_module.app.app_context():
                response = app_module.get_notification_worker_status()

        self.assertFalse(response.get_json()["notification_worker"]["running"])

    def test_live_worker_is_reported_as_running(self):
        app_module._notification_worker_state["running"] = True
        with patch.object(app_module, "_notification_worker_thread") as thread:
            thread.is_alive.return_value = True
            with app_module.app.app_context():
                response = app_module.get_notification_worker_status()

        self.assertTrue(response.get_json()["notification_worker"]["running"])


if __name__ == "__main__":
    unittest.main()
