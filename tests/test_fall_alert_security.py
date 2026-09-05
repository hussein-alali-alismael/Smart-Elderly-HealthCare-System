import os
import sys
import unittest
from unittest.mock import patch

os.environ["DISABLE_NOTIFICATION_WORKER"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app
from fall_alert_agent import FallDetectionPipeline, FallEventRecord


class FallAlertTests(unittest.TestCase):
    def test_default_backend_url_is_connectable(self):
        self.assertIn("http://127.0.0.1:", FallDetectionPipeline().backend_url)
        self.assertNotIn("0.0.0.0", FallDetectionPipeline().backend_url)

    @patch("app.FallDetectionPipeline")
    @patch.dict(os.environ, {"SEHCS_DEVICE_TOKEN": "test-fall-token"})
    def test_http_receiver_stores_without_dispatching_again(self, pipeline_class):
        event = FallEventRecord(
            resident_id=7,
            gravity_level="FALL",
            detected_at="2026-08-28T10:00:00",
        )
        pipeline = pipeline_class.return_value
        pipeline.node_1_receive_signal.return_value = event
        pipeline.node_2_verify_criticality.return_value = True
        pipeline.node_3_push_emergency_to_db.return_value = True
        pipeline.node_5_trigger_audio_alarm.return_value = True

        response = flask_app.test_client().post(
            "/api/fall-alerts",
            json={"event_type": "fall_detection", "data": {"gravity_level": "FALL"}},
            headers={"X-Fall-Alert-Token": "test-fall-token"},
        )

        self.assertEqual(response.status_code, 201)
        pipeline.node_1_receive_signal.assert_called_once()
        pipeline.node_2_verify_criticality.assert_called_once_with(event)
        pipeline.node_3_push_emergency_to_db.assert_called_once_with(event)
        pipeline.node_5_trigger_audio_alarm.assert_called_once_with(event)
        self.assertFalse(hasattr(pipeline, "process_fall_event") and pipeline.process_fall_event.called)

    @patch("fall_alert_agent.server_voice_enabled", return_value=True)
    @patch("fall_alert_agent.speak", return_value=True)
    def test_confirmed_fall_triggers_audio_alarm(self, speak_mock, voice_enabled_mock):
        pipeline = FallDetectionPipeline(backend_url="")
        event = FallEventRecord(resident_id=7, gravity_level="FALL", detected_at="now")

        result = pipeline.node_5_trigger_audio_alarm(event)

        self.assertTrue(result)
        voice_enabled_mock.assert_called_once_with()
        speak_mock.assert_called_once()
        self.assertIn("Fall detected for resident 7", speak_mock.call_args.args[0])
        self.assertEqual(speak_mock.call_args.kwargs, {"enabled": True})

    @patch("fall_alert_agent.speak")
    @patch("fall_alert_agent.server_voice_enabled", return_value=True)
    @patch("fall_alert_agent.threading.Thread")
    def test_model_json_is_announced_when_received(
        self, thread_class, voice_enabled_mock, speak_mock
    ):
        pipeline = FallDetectionPipeline(backend_url="")
        payload = {
            "gravity_level": "NO_FALL",
            "resident_id": 7,
            "confidence": 0.98,
        }

        pipeline.node_1_receive_signal(payload)

        thread_class.assert_called_once()
        self.assertTrue(thread_class.call_args.kwargs["daemon"])
        thread_class.return_value.start.assert_called_once_with()
        thread_class.call_args.kwargs["target"]()
        speak_mock.assert_called_once_with(
            "Fall detection update for resident 7: no fall detected.", enabled=True
        )
        voice_enabled_mock.assert_called_once_with()

    def test_boolean_fall_payload_is_normalized_for_alerting(self):
        pipeline = FallDetectionPipeline(backend_url="")

        event = pipeline.node_1_receive_signal({
            "resident_id": 7,
            "fall": True,
            "confidence": 1.4,
            "detected_at": "2026-08-28T10:00:00",
        })

        self.assertIsNotNone(event)
        self.assertEqual(event.gravity_level, "FALL")
        self.assertEqual(event.detection_confidence, 1.0)
        self.assertTrue(pipeline.node_2_verify_criticality(event))

    def test_falling_label_is_critical(self):
        pipeline = FallDetectionPipeline(backend_url="")
        event = pipeline.node_1_receive_signal({"gravity_level": "falling"})

        self.assertTrue(pipeline.node_2_verify_criticality(event))


if __name__ == "__main__":
    unittest.main()
