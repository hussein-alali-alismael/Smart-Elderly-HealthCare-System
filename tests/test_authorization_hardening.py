import os
import sys
import unittest
from unittest.mock import patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"
os.environ.pop("ENABLE_DEBUG_ROUTES", None)
os.environ["FLASK_SECRET_KEY"] = "replace-with-a-long-random-secret"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module
import repo


class FakeCursor:
    def __init__(self, fetchone_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.executions = []
        self.lastrowid = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        self.executions.append((query, params))

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, fetchone_values=None):
        self.cursor_instance = FakeCursor(fetchone_values)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass


class AuthorizationHardeningTests(unittest.TestCase):
    def test_placeholder_secret_is_replaced(self):
        with patch.dict(os.environ, {"FLASK_SECRET_KEY": "replace-with-a-long-random-secret"}):
            secure_app = app_module.create_app()

        self.assertNotEqual(secure_app.secret_key, "replace-with-a-long-random-secret")
        self.assertGreaterEqual(len(secure_app.secret_key), 64)

    def test_debug_route_is_disabled_by_default(self):
        self.assertIsNone(app_module.app.url_map._rules_by_endpoint.get("debug_list_routes"))

    @patch("repo.get_db_connection")
    def test_medical_conditions_query_is_scoped_to_user(self, get_connection):
        connection = FakeConnection()
        get_connection.return_value = connection

        with app_module.app.app_context():
            repo.list_resident_medical_conditions(user_id=12)

        query, params = connection.cursor_instance.executions[0]
        self.assertIn("WHERE r.user_id = %s", query)
        self.assertEqual(params, (12,))

    @patch("repo.get_db_connection")
    def test_fingerprint_update_checks_resident_owner(self, get_connection):
        connection = FakeConnection([{"id": 7}])
        get_connection.return_value = connection

        with app_module.app.app_context():
            repo.set_resident_fingerprint(7, "dGVzdA==", user_id=12)

        select_query, select_params = connection.cursor_instance.executions[0]
        update_query, update_params = connection.cursor_instance.executions[1]
        self.assertIn("AND user_id = %s", select_query)
        self.assertEqual(select_params, (7, 12))
        self.assertIn("WHERE id = %s AND user_id = %s", update_query)
        self.assertEqual(update_params, (b"test", 7, 12))


if __name__ == "__main__":
    unittest.main()
