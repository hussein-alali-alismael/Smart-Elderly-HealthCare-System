"""Fingerprint-driven medication intake agent.

This module is separate from ``ai_agent.py`` on purpose so the fingerprint
workflow stays easy to understand and does not get mixed with the chat/reminder
code.

Pipeline overview:
1. Receive a fingerprint template or sensor result from the AS608 reader.
2. Find the matching resident in ``elderly_residents`` using the stored
   ``fingerprintTemplate`` column.
3. Load today's active medication schedules for that resident.
4. If there is no medication for today, return a stop message.
5. Pick the nearest scheduled time to the current real time.
6. Upsert the matching intake row in ``medication_intakes``.

The agent is intentionally deterministic. The "AI" part here is the structured
node-style flow that decides what to do after fingerprint identification.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
import base64

from repo import get_db_connection

FingerprintInput = Union[bytes, bytearray, memoryview, str, int, Dict[str, Any]]


@dataclass
class FingerprintResident:
    id: int
    name: str
    fingerprintTemplate: Optional[bytes]


@dataclass
class MedicationScheduleRow:
    schedule_id: int
    resident_id: int
    resident_name: str
    medication_id: int
    medication_name: str
    medication_dosage: Optional[str]
    schedule_time_id: int
    time_of_day: str
    start_date: date
    end_date: Optional[date]
    is_active: int


@dataclass
class IntakeActionResult:
    success: bool
    message: str
    resident_id: Optional[int] = None
    resident_name: Optional[str] = None
    medication_schedule_time_id: Optional[int] = None
    medication_id: Optional[int] = None
    medication_name: Optional[str] = None
    planned_intake_datetime: Optional[str] = None
    actual_intake_datetime: Optional[str] = None
    intake_row_id: Optional[int] = None
    status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FingerprintMedicationAgent:
    """Node-based fingerprint workflow for medication intake confirmation."""

    def __init__(self, announcement_window_minutes: int = 10):
        self.announcement_window_minutes = announcement_window_minutes

    @staticmethod
    def _resident_to_dict(resident: FingerprintResident) -> Dict[str, Any]:
        """Return a JSON-safe resident result without exposing the template blob."""
        return {
            "id": resident.id,
            "name": resident.name,
            "fingerprintTemplateStored": resident.fingerprintTemplate is not None,
        }

    @staticmethod
    def _schedule_to_dict(schedule: MedicationScheduleRow) -> Dict[str, Any]:
        """Return a JSON-safe schedule result."""
        result = asdict(schedule)
        for key in ("start_date", "end_date"):
            value = result.get(key)
            if isinstance(value, (date, datetime)):
                result[key] = value.isoformat()
        return result

    @staticmethod
    def _normalize_fingerprint_input(fingerprint_input: FingerprintInput) -> Tuple[str, Any]:
        """Normalize the sensor output into a comparison mode and value.

        The AS608 may later return a raw template, an enrolled number, or a small
        payload dictionary. This method keeps the agent flexible until the exact
        sensor response is confirmed.
        """
        if isinstance(fingerprint_input, dict):
            # Authenticated sensor payloads should prefer the trusted slot mapping,
            # because AS608 template bytes vary per scan even for the same finger.
            for key in ("resident_id", "residentId"):
                if key in fingerprint_input and fingerprint_input[key] is not None:
                    return "resident_id", fingerprint_input[key]

            for key in ("fingerprintSensorSlot", "sensor_position", "sensorPosition"):
                if key in fingerprint_input and fingerprint_input[key] is not None:
                    return "sensor_slot", int(fingerprint_input[key])

            for key in ("fingerprintTemplate", "template"):
                if key in fingerprint_input and fingerprint_input[key] is not None:
                    return key, fingerprint_input[key]

            for key in ("fingerprint_id", "fingerprintId", "id"):
                if key in fingerprint_input and fingerprint_input[key] is not None:
                    return "untrusted_numeric", fingerprint_input[key]

            raise ValueError("Fingerprint payload dictionary does not contain a usable identifier.")

        if isinstance(fingerprint_input, (bytes, bytearray, memoryview)):
            return "binary_template", bytes(fingerprint_input)

        if isinstance(fingerprint_input, int):
            return "resident_id", fingerprint_input

        text_value = str(fingerprint_input).strip()
        if not text_value:
            raise ValueError("Fingerprint input is empty.")

        if text_value.isdigit():
            return "resident_id", int(text_value)

        # If the input is a base64-encoded template, decode and treat as binary
        try:
            decoded = base64.b64decode(text_value, validate=True)
            if decoded:
                return "binary_template", decoded
        except Exception:
            pass

        return "text_template", text_value

    def node_1_find_resident_by_fingerprint(self, fingerprint_input: FingerprintInput) -> Optional[FingerprintResident]:
        """Find the resident that matches the fingerprint input."""
        if isinstance(fingerprint_input, (int, str)):
            text_value = str(fingerprint_input).strip()
            if text_value.isdigit() or (text_value.startswith("-") and text_value[1:].isdigit()):
                return None

        mode, value = self._normalize_fingerprint_input(fingerprint_input)
        if mode == "untrusted_numeric":
            return None

        connection = get_db_connection()
        if connection is None:
            return None

        query = """
            SELECT id, name, fingerprintTemplate, fingerprintSensorSlot
            FROM elderly_residents
            WHERE fingerprintTemplate IS NOT NULL
        """
        params: Tuple[Any, ...] = ()

        if mode == "resident_id":
            query = """
                SELECT id, name, fingerprintTemplate, fingerprintSensorSlot
                FROM elderly_residents
                WHERE id = %s
                LIMIT 1
            """
            params = (value,)
        elif mode == "sensor_slot":
            query = """
                SELECT id, name, fingerprintTemplate, fingerprintSensorSlot
                FROM elderly_residents
                WHERE fingerprintSensorSlot = %s
                LIMIT 1
            """
            params = (value,)
        elif mode == "binary_template":
            query += " AND fingerprintTemplate = %s LIMIT 1"
            params = (value,)
        else:
            # Allow future template storage formats like hex/base64 text while we
            # are still testing the AS608 sensor output.
            query += " AND CAST(fingerprintTemplate AS CHAR) = %s LIMIT 1"
            params = (str(value),)

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()

        if row is None:
            return None

        return FingerprintResident(
            id=row["id"],
            name=row.get("name") or "Unknown resident",
            fingerprintTemplate=row.get("fingerprintTemplate"),
        )

    def node_2_check_resident_match(self, resident: Optional[FingerprintResident]) -> Tuple[bool, str]:
        """Return a stop message when no resident is found."""
        if resident is None:
            return False, "Wrong check-in: fingerprint was not recognized. Waiting for the next scan."
        return True, f"Resident matched: {resident.name} (ID {resident.id})."

    def node_3_load_today_medication_schedules(self, resident_id: int, now: Optional[datetime] = None) -> List[MedicationScheduleRow]:
        """Load today's active medication schedule times for the resident."""
        now = now or datetime.now()
        today = now.date().isoformat()
        connection = get_db_connection()
        if connection is None:
            return []

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ms.id AS schedule_id,
                       ms.residentId AS resident_id,
                       r.name AS resident_name,
                       ms.medicationId AS medication_id,
                       m.name AS medication_name,
                       m.dosage AS medication_dosage,
                       mst.id AS schedule_time_id,
                       TIME_FORMAT(mst.timeOfDay, '%%H:%%i:%%s') AS time_of_day,
                       ms.startDate AS start_date,
                       ms.endDate AS end_date,
                       ms.isActive AS is_active
                FROM medication_schedules ms
                INNER JOIN medication_schedule_times mst ON mst.scheduleId = ms.id
                LEFT JOIN elderly_residents r ON r.id = ms.residentId
                LEFT JOIN medications m ON m.id = ms.medicationId
                WHERE ms.residentId = %s
                  AND ms.isActive = 1
                  AND ms.startDate <= %s
                  AND (ms.endDate IS NULL OR ms.endDate >= %s)
                ORDER BY mst.timeOfDay ASC, ms.id ASC
                """,
                (resident_id, today, today),
            )
            rows = cursor.fetchall() or []

        schedules: List[MedicationScheduleRow] = []
        for row in rows:
            schedules.append(
                MedicationScheduleRow(
                    schedule_id=row["schedule_id"],
                    resident_id=row["resident_id"],
                    resident_name=row.get("resident_name") or "Unknown resident",
                    medication_id=row["medication_id"],
                    medication_name=row.get("medication_name") or "Unknown medication",
                    medication_dosage=row.get("medication_dosage"),
                    schedule_time_id=row["schedule_time_id"],
                    time_of_day=str(row.get("time_of_day") or "00:00:00"),
                    start_date=row.get("start_date") or now.date(),
                    end_date=row.get("end_date"),
                    is_active=int(row.get("is_active") or 0),
                )
            )
        return schedules

    def node_4_check_today_medication_exists(self, schedules: List[MedicationScheduleRow]) -> Tuple[bool, str]:
        """Return a stop message if there is no medication scheduled for today."""
        if not schedules:
            return False, "No medication is scheduled for today."
        return True, f"Found {len(schedules)} medication schedule time(s) for today."

    @staticmethod
    def _planned_datetime_for_today(now: datetime, time_of_day: str) -> datetime:
        schedule_time = datetime.strptime(time_of_day, "%H:%M:%S").time()
        candidate = datetime.combine(now.date(), schedule_time)
        if candidate - now > timedelta(hours=12):
            candidate -= timedelta(days=1)
        elif now - candidate > timedelta(hours=12):
            candidate += timedelta(days=1)
        return candidate

    def node_5_choose_nearest_medication_time(
        self,
        schedules: List[MedicationScheduleRow],
        now: Optional[datetime] = None,
    ) -> Optional[MedicationScheduleRow]:
        """Pick the schedule row whose time is nearest to the current real time."""
        now = now or datetime.now()
        if not schedules:
            return None

        def distance_minutes(row: MedicationScheduleRow) -> float:
            planned = self._planned_datetime_for_today(now, row.time_of_day)
            return abs((planned - now).total_seconds()) / 60.0

        nearest = min(schedules, key=distance_minutes)
        if distance_minutes(nearest) > self.announcement_window_minutes:
            return None
        return nearest

    def final_node_upsert_intake_log(
        self,
        resident: FingerprintResident,
        schedule: MedicationScheduleRow,
        now: Optional[datetime] = None,
    ) -> IntakeActionResult:
        """Insert a new intake row or update an existing one."""
        now = now or datetime.now()
        connection = get_db_connection()
        if connection is None:
            return IntakeActionResult(success=False, message="Database is not available.")

        planned_datetime = self._planned_datetime_for_today(now, schedule.time_of_day)
        actual_datetime_text = now.strftime("%Y-%m-%d %H:%M:%S")
        planned_datetime_text = planned_datetime.strftime("%Y-%m-%d %H:%M:%S")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, status, actualIntakeDateTime
                FROM medication_intakes
                WHERE medicationScheduleTimeId = %s
                  AND DATE(plannedIntakeDateTime) = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (schedule.schedule_time_id, planned_datetime.date().isoformat()),
            )
            existing = cursor.fetchone()

            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO medication_intakes (
                        medicationScheduleTimeId,
                        plannedIntakeDateTime,
                        actualIntakeDateTime,
                        status,
                        actualDosage,
                        confirmedByFingerprintAt,
                        confirmedByUserAt,
                        notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        schedule.schedule_time_id,
                        planned_datetime_text,
                        actual_datetime_text,
                        "taken",
                        schedule.medication_dosage,
                        actual_datetime_text,
                        None,
                        f"Fingerprint check-in for resident {resident.id}.",
                    ),
                )
                intake_row_id = cursor.lastrowid
            elif existing.get("status") == "taken":
                # A second scan is an idempotent confirmation. Preserve the
                # first actual intake time instead of overwriting the evidence.
                intake_row_id = existing["id"]
                actual_datetime_text = str(existing.get("actualIntakeDateTime") or actual_datetime_text)
            else:
                intake_row_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE medication_intakes
                    SET actualIntakeDateTime = %s,
                        status = %s,
                        actualDosage = %s,
                        confirmedByFingerprintAt = %s,
                        notes = %s
                    WHERE id = %s
                    """,
                    (
                        actual_datetime_text,
                        "taken",
                        schedule.medication_dosage,
                        actual_datetime_text,
                        f"Fingerprint check-in updated for resident {resident.id}.",
                        intake_row_id,
                    ),
                )

        connection.commit()

        return IntakeActionResult(
            success=True,
            message="Medication intake recorded successfully.",
            resident_id=resident.id,
            resident_name=resident.name,
            medication_schedule_time_id=schedule.schedule_time_id,
            medication_id=schedule.medication_id,
            medication_name=schedule.medication_name,
            planned_intake_datetime=planned_datetime_text,
            actual_intake_datetime=actual_datetime_text,
            intake_row_id=intake_row_id,
            status="taken",
        )

    def process_fingerprint(self, fingerprint_input: FingerprintInput, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Run the full node pipeline for a single fingerprint input."""
        now = now or datetime.now()
        resident = self.node_1_find_resident_by_fingerprint(fingerprint_input)
        matched, message = self.node_2_check_resident_match(resident)
        if not matched or resident is None:
            return {
                "success": False,
                "step": "resident_lookup",
                "message": message,
                "resident": None,
                "result": None,
            }

        schedules = self.node_3_load_today_medication_schedules(resident.id, now=now)
        has_today, today_message = self.node_4_check_today_medication_exists(schedules)
        if not has_today:
            return {
                "success": False,
                "step": "today_schedule_check",
                "message": today_message,
                "resident": self._resident_to_dict(resident),
                "result": None,
            }

        nearest_schedule = self.node_5_choose_nearest_medication_time(schedules, now=now)
        if nearest_schedule is None:
            return {
                "success": False,
                "step": "nearest_schedule_selection",
                "message": "No medication time is close enough to the current real time.",
                "resident": self._resident_to_dict(resident),
                "result": None,
            }

        result = self.final_node_upsert_intake_log(resident, nearest_schedule, now=now)
        return {
            "success": result.success,
            "step": "final",
            "message": result.message,
                "resident": self._resident_to_dict(resident),
                "schedule": self._schedule_to_dict(nearest_schedule),
            "result": result.to_dict(),
        }


__all__ = [
    "FingerprintMedicationAgent",
    "FingerprintResident",
    "MedicationScheduleRow",
    "IntakeActionResult",
]
