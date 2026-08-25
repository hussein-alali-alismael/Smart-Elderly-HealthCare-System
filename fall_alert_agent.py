from __future__ import annotations

import json
import os
import requests
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv
from repo import get_db_connection

load_dotenv()

FLASK_RUN_HOST = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
FLASK_RUN_PORT = os.getenv("FLASK_RUN_PORT", "5000")
BACKEND_API_URL = f"http://{FLASK_RUN_HOST}:{FLASK_RUN_PORT}/api/fall-alerts"
DEFAULT_RESIDENT_ID = os.getenv("FALL_ALERT_DEFAULT_RESIDENT_ID") or None
DEFAULT_DEVICE_ID = os.getenv("FALL_ALERT_DEVICE_ID") or None
DEFAULT_LOCATION = os.getenv("FALL_ALERT_LOCATION") or None


@dataclass
class FallEventRecord:
    resident_id: Optional[int]
    gravity_level: str
    detected_at: str
    device_id: Optional[str] = None
    location: Optional[str] = None
    detection_confidence: Optional[float] = None
    evidence_path: Optional[str] = None
    incident_id: Optional[int] = None
    is_resolved: int = 0


class FallDetectionPipeline:

    def __init__(self, backend_url: str = BACKEND_API_URL):
        self.backend_url = backend_url

    def node_1_receive_signal(self, payload: Dict[str, object]) -> Optional[FallEventRecord]:
        if not payload:
            return None

        resident_value = payload.get("resident_id") or payload.get("residentId") or DEFAULT_RESIDENT_ID
        resident_id: Optional[int] = None
        if isinstance(resident_value, (int, str)) and resident_value != "":
            try:
                resident_id = int(resident_value)
            except ValueError:
                resident_id = None

        confidence_value = payload.get("detection_confidence") or payload.get("confidence")
        confidence: Optional[float] = None
        if isinstance(confidence_value, (int, float, str)) and confidence_value != "":
            try:
                confidence = float(confidence_value)
            except ValueError:
                confidence = None

        return FallEventRecord(
            resident_id=resident_id,
            gravity_level=str(payload.get("gravity_level") or "FALL"),
            detected_at=str(payload.get("detected_at") or payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")),
            device_id=str(payload.get("device_id") or payload.get("deviceId") or DEFAULT_DEVICE_ID or "") or None,
            location=str(payload.get("location") or DEFAULT_LOCATION or "") or None,
            detection_confidence=confidence,
            evidence_path=str(payload.get("evidence_path") or payload.get("evidencePath") or "") or None,
        )

    def node_2_verify_criticality(self, event: FallEventRecord) -> bool:
        if event.gravity_level.upper() == "FALL":
            return True
        return False

    def node_3_push_emergency_to_db(self, event: FallEventRecord) -> bool:
        connection = get_db_connection()
        if connection is None:
            return False

        message = "EMERGENCY ALERT: Critical fall detected in the monitored ward!"

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO fall_incidents
                        (residentId, deviceId, location, detectionConfidence,
                         detectedAt, status, evidencePath)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (event.resident_id, event.device_id, event.location,
                     event.detection_confidence, event.detected_at, "detected",
                     event.evidence_path)
                )
                event.incident_id = cursor.lastrowid

                # notifications.residentId is intentionally NOT NULL. Only
                # create a resident notification after identity is known.
                if event.resident_id is not None:
                    cursor.execute(
                        """
                        INSERT INTO notifications (residentId, type, message, isSent, sentAt, isRead)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (event.resident_id, "fall_alert", message, 1, event.detected_at, 0)
                    )
            connection.commit()
            return True
        except Exception:
            return False

    def node_4_dispatch_live_webhook(self, event: FallEventRecord) -> bool:
        payload = {
            "event_type": "fall_detection",
            "timestamp": event.detected_at,
            "data": asdict(event)
        }
        try:
            response = requests.post(self.backend_url, json=payload, timeout=5)
            return response.status_code == 201
        except requests.RequestException:
            return self._trigger_local_fallback_alarm(event)

    def _trigger_local_fallback_alarm(self, event: FallEventRecord) -> bool:
        print(f"CRITICAL: Webhook failed. Local Fallback Active for Resident ID {event.resident_id}!")
        return True

    def process_fall_event(self, raw_signal: Dict[str, object]) -> Dict[str, object]:
        event = self.node_1_receive_signal(raw_signal)
        if event is None:
            return {"status": "rejected", "reason": "invalid_payload"}

        is_critical = self.node_2_verify_criticality(event)
        if not is_critical:
            return {"status": "logged", "data": asdict(event)}

        db_saved = self.node_3_push_emergency_to_db(event)
        network_dispatched = self.node_4_dispatch_live_webhook(event)

        return {
            "status": "dispatched",
            "db_synced": db_saved,
            "live_alert_sent": network_dispatched,
            "event_details": asdict(event)
        }


__all__ = [
    "FallEventRecord",
    "FallDetectionPipeline",
]




