import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app


class SmartElderlyHealthCareTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_create_patient(self):
        payload = {
            "name": "Mary James",
            "age": 78,
            "condition": "Hypertension",
        }
        response = self.client.post("/api/patients", json=payload)
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["name"], "Mary James")
        self.assertIn("id", body)

    def test_alerts_endpoint(self):
        self.client.post("/api/patients", json={"name": "John Doe", "age": 82, "condition": "Diabetes"})
        self.client.post("/api/vitals/1", json={"heart_rate": 118, "blood_pressure": "180/100", "temperature": 38.5})
        response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["alerts"])

    def test_create_medication(self):
        response = self.client.post("/api/medications", json={
            "name": "Paracetamol",
            "dosage": "500mg",
            "form": "Tablet",
            "manufacturer": "Test Pharma",
            "side_effects": "Drowsiness",
            "instructions": "Take after meals",
            "contraindications": "Liver disease",
        })
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["name"], "Paracetamol")
        self.assertEqual(body["sideEffects"], "Drowsiness")
        self.assertEqual(body["instructions"], "Take after meals")

    def test_update_medication(self):
        create_response = self.client.post("/api/medications", json={
            "name": "Ibuprofen",
            "dosage": "200mg",
            "form": "Tablet",
            "manufacturer": "Old Pharma",
        })
        medication_id = create_response.get_json()["id"]

        update_response = self.client.put(f"/api/medications/{medication_id}", json={
            "name": "Ibuprofen",
            "dosage": "400mg",
            "form": "Tablet",
            "manufacturer": "New Pharma",
            "side_effects": "Upset stomach",
            "instructions": "Take with food",
            "contraindications": "Kidney disease",
        })

        self.assertEqual(update_response.status_code, 200)
        body = update_response.get_json()
        self.assertEqual(body["dosage"], "400mg")
        self.assertEqual(body["manufacturer"], "New Pharma")
        self.assertEqual(body["status"], "updated")


if __name__ == "__main__":
    unittest.main()
