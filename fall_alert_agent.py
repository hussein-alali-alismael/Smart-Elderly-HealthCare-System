from __future__ import annotations

import os
import hashlib
import json
import logging
import math
import requests
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional

from dotenv import load_dotenv
from repo import get_db_connection
from voice import server_voice_enabled, speak

load_dotenv()

BACKEND_API_HOST = os.getenv("BACKEND_API_HOST", "127.0.0.1")
BACKEND_API_PORT = os.getenv("FLASK_RUN_PORT", os.getenv("PORT", "5000"))
BACKEND_API_URL = os.getenv(
    "BACKEND_API_URL",
    f"http://{BACKEND_API_HOST}:{BACKEND_API_PORT}/api/fall-alerts",
)
DEFAULT_RESIDENT_ID = os.getenv("FALL_ALERT_DEFAULT_RESIDENT_ID") or None
DEFAULT_DEVICE_ID = os.getenv("FALL_ALERT_DEVICE_ID") or None
DEFAULT_LOCATION = os.getenv("FALL_ALERT_LOCATION") or None


def _speak_async(text: str) -> None:
    """Start model-result speech without blocking fall-event processing."""
    def speak_safely() -> None:
        try:
            speak(text, enabled=server_voice_enabled())
        except Exception:
            # Speech must never prevent the event from being stored or alerted.
            pass

    threading.Thread(target=speak_safely, daemon=True).start()


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
    event_id: Optional[str] = None
    is_duplicate: bool = False


class FallDetectionPipeline:

    @staticmethod
    def _is_fall_level(value: object) -> bool:
        return str(value or "").strip().upper() in {
            "FALL", "FALLING", "FALLEN", "CRITICAL_FALL", "FALL_DETECTED",
        }

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

        confidence_value = payload.get("detection_confidence")
        if confidence_value is None:
            confidence_value = payload.get("confidence")
        confidence: Optional[float] = None
        if isinstance(confidence_value, (int, float, str)) and confidence_value != "":
            try:
                parsed_confidence = float(confidence_value)
                if math.isfinite(parsed_confidence):
                    confidence = max(0.0, min(1.0, parsed_confidence))
            except ValueError:
                confidence = None

        gravity_value = payload.get("gravity_level") or payload.get("gravityLevel")
        if gravity_value is None:
            fall_value = payload.get("fall", payload.get("is_fall", False))
            status = str(payload.get("status") or "").strip().upper()
            gravity_value = "FALL" if fall_value is True or status in {"FALL", "FALLING", "FALL_DETECTED"} else "NO_FALL"
        gravity_level = "FALL" if self._is_fall_level(gravity_value) else str(gravity_value).strip().upper()

        event = FallEventRecord(
            resident_id=resident_id,
            gravity_level=gravity_level or "FALL",
            detected_at=str(payload.get("detected_at") or payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")),
            device_id=str(payload.get("device_id") or payload.get("deviceId") or DEFAULT_DEVICE_ID or "") or None,
            location=str(payload.get("location") or DEFAULT_LOCATION or "") or None,
            detection_confidence=confidence,
            evidence_path=str(payload.get("evidence_path") or payload.get("evidencePath") or "") or None,
            event_id=str(payload.get("event_id") or payload.get("eventId") or payload.get("idempotency_key") or payload.get("idempotencyKey") or "") or None,
        )
        if event.event_id is None:
            event.event_id = hashlib.sha256(json.dumps({
                "resident_id": event.resident_id,
                "gravity_level": event.gravity_level,
                "detected_at": event.detected_at,
                "device_id": event.device_id,
                "location": event.location,
                "detection_confidence": event.detection_confidence,
                "evidence_path": event.evidence_path,
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        resident = f" for resident {event.resident_id}" if event.resident_id is not None else ""
        if self._is_fall_level(event.gravity_level):
            message = f"Emergency! Fall detected{resident}. Please provide assistance immediately."
        else:
            message = f"Fall detection update{resident}: no fall detected."
        # Non-critical model updates may be spoken immediately. Confirmed
        # falls are announced once by node 5 after they are persisted.
        if not self._is_fall_level(event.gravity_level):
            _speak_async(message)
        return event

    def node_2_verify_criticality(self, event: FallEventRecord) -> bool:
        return self._is_fall_level(event.gravity_level)

    def node_3_push_emergency_to_db(
        self,
        event: FallEventRecord,
        create_notification: bool = True,
    ) -> bool:
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
                        detectedAt, status, evidencePath, eventId)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (event.resident_id, event.device_id, event.location,
                     event.detection_confidence, event.detected_at, "detected",
                     event.evidence_path, event.event_id)
                )
                event.incident_id = cursor.lastrowid

                # notifications.residentId is intentionally NOT NULL. Only
                # create a resident notification after identity is known.
                if create_notification and event.resident_id is not None:
                    cursor.execute(
                        """
                        INSERT INTO notifications (residentId, type, message, isSent, sentAt, isRead)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (event.resident_id, "fall_alert", message, 1, event.detected_at, 0)
                    )
            connection.commit()
            return True
        except Exception as exc:
            logging.exception("Could not persist fall incident")
            if getattr(exc, "args", [None])[0] == 1062:
                event.is_duplicate = True
                connection.rollback()
                return True
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

    def node_5_trigger_audio_alarm(self, event: FallEventRecord) -> bool:
        """Announce a confirmed fall through the server's configured speaker."""
        resident = f" for resident {event.resident_id}" if event.resident_id is not None else ""
        message = f"Emergency! Fall detected{resident}. Please provide assistance immediately."
        return speak(message, enabled=server_voice_enabled())

    def _trigger_local_fallback_alarm(self, event: FallEventRecord) -> bool:
        print(f"CRITICAL: Webhook failed. Local Fallback Active for Resident ID {event.resident_id}!")
        return True

    def process_fall_event(self, raw_signal: Dict[str, object]) -> Dict[str, object]:
        event = self.node_1_receive_signal(raw_signal)
        if event is None:
            return {"status": "rejected", "reason": "invalid_payload"}

        is_critical = self.node_2_verify_criticality(event)
        if not is_critical:
            db_saved = self.node_3_push_emergency_to_db(event, create_notification=False)
            return {"status": "logged", "db_synced": db_saved, "data": asdict(event)}

        db_saved = self.node_3_push_emergency_to_db(event)
        audio_alerted = self.node_5_trigger_audio_alarm(event)
        network_dispatched = self.node_4_dispatch_live_webhook(event)

        return {
            "status": "dispatched",
            "db_synced": db_saved,
            "audio_alerted": audio_alerted,
            "live_alert_sent": network_dispatched,
            "event_details": asdict(event)
        }


__all__ = [
    "FallEventRecord",
    "FallDetectionPipeline",
]




