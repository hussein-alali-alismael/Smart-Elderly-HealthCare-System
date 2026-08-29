import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DISABLE_NOTIFICATION_WORKER", "1")

from app import app


class CrudRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_crud_routes_are_registered(self):
        routes = {}
        for rule in app.url_map.iter_rules():
            routes.setdefault(str(rule), set()).update(rule.methods or ())
        expected = {
            "/api/residents/<int:resident_id>": {"GET", "PUT", "PATCH", "DELETE"},
            "/api/medications/<int:medication_id>": {"GET", "PUT", "PATCH", "DELETE"},
            "/api/medication-schedules/<int:schedule_id>": {"GET", "PUT", "PATCH", "DELETE"},
            "/api/medication-schedules/<int:schedule_id>/times": {"GET", "POST"},
            "/api/medication-intakes/<int:intake_id>": {"GET", "PUT", "PATCH"},
            "/api/notifications/<int:notification_id>": {"GET", "DELETE"},
            "/api/fall-incidents/<int:incident_id>": {"GET", "PUT", "PATCH"},
        }
        for path, methods in expected.items():
            self.assertIn(path, routes)
            self.assertTrue(methods.issubset(routes[path]))

    def test_crud_routes_require_login(self):
        for path, method in [
            ("/api/residents/1", "GET"),
            ("/api/medications/1", "DELETE"),
            ("/api/medication-schedules", "POST"),
            ("/api/notifications/1/read", "PATCH"),
            ("/api/fall-incidents", "GET"),
        ]:
            response = self.client.open(path, method=method)
            self.assertEqual(response.status_code, 401, (method, path))


if __name__ == "__main__":
    unittest.main()
