"""Medication scheduling agent + local Gemini chatbot with memory.

This module provides two pieces:
1. A LangChain + Gemini chatbot with per-session memory for Streamlit.
2. A medication reminder pipeline that:
   - loads schedule times,
   - checks whether each schedule is within the 10-minute announcement window,
   - writes notifications into the `notifications` table,
   - builds a JSON payload for the web dashboard.

The pipeline is intentionally written as small node-like methods so it is easy
for a beginner to understand and extend.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from dotenv import load_dotenv
from flask import jsonify
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_google_genai import ChatGoogleGenerativeAI

from repo import get_db_connection
from voice import server_voice_enabled, speak

load_dotenv()

ANNOUNCEMENT_WINDOW_MINUTES = int(os.getenv("ANNOUNCEMENT_WINDOW_MINUTES", "10"))
MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "300"))
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


def _speak_async(text: str) -> None:
    """Start speech without blocking the scheduler worker."""
    def speak_safely() -> None:
        try:
            speak(text, enabled=server_voice_enabled())
        except Exception:
            # A TTS failure must never stop future medication reminders.
            pass

    threading.Thread(target=speak_safely, daemon=True).start()


@dataclass
class ScheduleRecord:
    schedule_id: int
    resident_id: int
    resident_name: str
    medication_id: int
    medication_name: str
    frequency: str
    start_date: str
    end_date: Optional[str]
    schedule_time_id: int
    time_of_day: str


@dataclass
class NotificationRecord:
    residentId: int
    type: str
    message: str
    isSent: int = 1
    sentAt: str = ""
    isRead: int = 0
    readAt: Optional[str] = None

    def to_db_tuple(self) -> tuple:
        return (
            self.residentId,
            self.type,
            self.message,
            self.isSent,
            self.sentAt,
            self.isRead,
            self.readAt,
        )


class MedicationAssistant:
    """Local chatbot with conversational memory backed by Gemini."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = DEFAULT_MODEL):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model_name
        self._histories: Dict[str, InMemoryChatMessageHistory] = {}
        # Gemini is optional. Delay client construction until the feature is
        # actually used, so the Flask/Streamlit app can start without a key.
        self._chain = None

    def _build_chain(self):
        if not self.api_key:
            return None

        model = ChatGoogleGenerativeAI(
            model=self.model_name,
            temperature=0.6,
            google_api_key=self.api_key,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful healthcare operations assistant. "
                    "Be concise, supportive, and explain things clearly for beginners. "
                    "If asked about medication schedules or reminders, answer using the provided context.",
                ),
                MessagesPlaceholder(variable_name="history"),
                ("human", "{input}"),
            ]
        )
        return RunnableWithMessageHistory(
            prompt | model,
            self._get_history,
            input_messages_key="input",
            history_messages_key="history",
        )

    def _get_history(self, session_id: str) -> InMemoryChatMessageHistory:
        if session_id not in self._histories:
            self._histories[session_id] = InMemoryChatMessageHistory()
        return self._histories[session_id]

    def ask(self, message: str, session_id: str = "default") -> str:
        if not self.api_key:
            return "The Gemini assistant is unavailable because GEMINI_API_KEY is not configured."

        if self._chain is None:
            self._chain = self._build_chain()
        if self._chain is None:
            return "The Gemini assistant is unavailable because GEMINI_API_KEY is not configured."

        response = self._chain.invoke(
            {"input": message},
            config={"configurable": {"session_id": session_id}},
        )
        answer = getattr(response, "content", str(response))
        return answer


class MedicationSchedulerAgent:
    """Medication reminder pipeline for the 10-minute announcement window."""

    def __init__(self, announcement_window_minutes: int = ANNOUNCEMENT_WINDOW_MINUTES):
        self.announcement_window_minutes = announcement_window_minutes
        self._stop_event = threading.Event()

    def node_1_load_schedule_time(self) -> List[ScheduleRecord]:
        """Load schedule times from the database."""
        connection = get_db_connection()
        if connection is None:
            return []

        today = datetime.now().date().isoformat()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ms.id AS schedule_id,
                       ms.residentId AS resident_id,
                       r.name AS resident_name,
                       ms.medicationId AS medication_id,
                       m.name AS medication_name,
                       ms.frequency,
                       ms.startDate,
                       ms.endDate,
                       mst.id AS schedule_time_id,
                       mst.timeOfDay
                FROM medication_schedules ms
                LEFT JOIN elderly_residents r ON r.id = ms.residentId
                LEFT JOIN medications m ON m.id = ms.medicationId
                INNER JOIN medication_schedule_times mst ON mst.scheduleId = ms.id
                                WHERE ms.isActive = 1
                                    AND ms.startDate <= %s
                                    AND (ms.endDate IS NULL OR ms.endDate >= %s)
                ORDER BY ms.id ASC, mst.timeOfDay ASC
                                """,
                                (today, today),
            )
            rows = cursor.fetchall() or []

        schedules: List[ScheduleRecord] = []
        for row in rows:
            schedules.append(
                ScheduleRecord(
                    schedule_id=row["schedule_id"],
                    resident_id=row["resident_id"],
                    resident_name=row.get("resident_name") or "Unknown resident",
                    medication_id=row["medication_id"],
                    medication_name=row.get("medication_name") or "Unknown medication",
                    frequency=row.get("frequency") or "unknown",
                    start_date=str(row.get("startDate") or ""),
                    end_date=str(row.get("endDate")) if row.get("endDate") else None,
                    schedule_time_id=row["schedule_time_id"],
                    time_of_day=str(row.get("timeOfDay") or "00:00:00"),
                )
            )
        return schedules

    @staticmethod
    def _nearest_occurrence(now: datetime, time_of_day: str) -> datetime:
        schedule_time = datetime.strptime(time_of_day, "%H:%M:%S").time()
        candidate = datetime.combine(now.date(), schedule_time)
        if candidate - now > timedelta(hours=12):
            candidate -= timedelta(days=1)
        elif now - candidate > timedelta(hours=12):
            candidate += timedelta(days=1)
        return candidate

    def node_2_check_if_suitable_to_announce(self, schedule: ScheduleRecord, now: Optional[datetime] = None) -> Optional[datetime]:
        """Return the planned datetime when the reminder is within the announcement window."""
        now = now or datetime.now()
        planned_datetime = self._nearest_occurrence(now, schedule.time_of_day)
        delta_minutes = abs((planned_datetime - now).total_seconds()) / 60.0
        if delta_minutes <= self.announcement_window_minutes:
            return planned_datetime
        return None

    def node_3_sync_daily_intake_statuses(
        self,
        schedules: List[ScheduleRecord],
        now: Optional[datetime] = None,
    ) -> None:
        """Create today's pending intakes and mark expired pending intakes missed."""
        connection = get_db_connection()
        if connection is None:
            return

        now = now or datetime.now()
        today = now.date().isoformat()
        missed_before = now - timedelta(minutes=self.announcement_window_minutes)

        with connection.cursor() as cursor:
            for schedule in schedules:
                planned_datetime = datetime.combine(
                    now.date(),
                    datetime.strptime(schedule.time_of_day, "%H:%M:%S").time(),
                )
                planned_text = planned_datetime.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    """
                    SELECT id, status
                    FROM medication_intakes
                    WHERE medicationScheduleTimeId = %s
                      AND DATE(plannedIntakeDateTime) = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (schedule.schedule_time_id, today),
                )
                existing = cursor.fetchone()

                if existing is None:
                    initial_status = "missed" if planned_datetime <= missed_before else "pending"
                    cursor.execute(
                        """
                        INSERT INTO medication_intakes
                            (medicationScheduleTimeId, plannedIntakeDateTime, status)
                        VALUES (%s, %s, %s)
                        """,
                        (schedule.schedule_time_id, planned_text, initial_status),
                    )
                elif existing.get("status") == "pending" and planned_datetime <= missed_before:
                    cursor.execute(
                        """
                        UPDATE medication_intakes
                        SET status = %s
                        WHERE id = %s
                        """,
                        ("missed", existing["id"]),
                    )

    def _notification_exists(
        self,
        connection,
        resident_id: int,
        notification_type: str,
        message: str,
        notification_date: Optional[str] = None,
    ) -> bool:
        notification_date = notification_date or datetime.now().date().isoformat()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM notifications
                WHERE residentId = %s
                  AND type = %s
                  AND message = %s
                  AND DATE(sentAt) = %s
                LIMIT 1
                """,
                (resident_id, notification_type, message, notification_date),
            )
            return cursor.fetchone() is not None

    def node_3_build_notification_in_table(self, schedule: ScheduleRecord, planned_datetime: datetime, now: Optional[datetime] = None) -> Optional[NotificationRecord]:
        """Insert a notification row unless it already exists."""
        connection = get_db_connection()
        if connection is None:
            return None

        now = now or datetime.now()
        notification_type = "medication_reminder"
        spoken_time = planned_datetime.strftime("%I:%M %p").lstrip("0")
        message = (
            f"Reminder for {schedule.resident_name}: it is time to take "
            f"{schedule.medication_name} at {spoken_time}."
        )

        if self._notification_exists(
            connection,
            schedule.resident_id,
            notification_type,
            message,
            notification_date=now.date().isoformat(),
        ):
            return None

        record = NotificationRecord(
            residentId=schedule.resident_id,
            type=notification_type,
            message=message,
            sentAt=now.isoformat(timespec="seconds"),
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO notifications (residentId, type, message, isSent, sentAt, isRead, readAt)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                record.to_db_tuple(),
            )
        connection.commit()
        return record

    def node_4_make_text_json_for_webdash(
        self,
        schedule: ScheduleRecord,
        planned_datetime: datetime,
        notification: NotificationRecord,
        now: Optional[datetime] = None,
    ) -> Dict[str, object]:
        """Create a JSON payload for the dashboard."""
        now = now or datetime.now()
        payload = {
            "generated_at": now.isoformat(timespec="seconds"),
            "status": "ready",
            "announcement_window_minutes": self.announcement_window_minutes,
            "schedule": asdict(schedule),
            "planned_intake_datetime": planned_datetime.isoformat(timespec="seconds"),
            "spoken_message": notification.message,
            "notification": asdict(notification),
        }
        return payload

    def run_once(self) -> List[Dict[str, object]]:
        """Run the pipeline one time and return the dashboard payloads."""
        now = datetime.now()
        payloads: List[Dict[str, object]] = []
        schedules = self.node_1_load_schedule_time()
        self.node_3_sync_daily_intake_statuses(schedules, now=now)

        for schedule in schedules:
            planned_datetime = self.node_2_check_if_suitable_to_announce(schedule, now=now)
            if planned_datetime is None:
                continue

            notification = self.node_3_build_notification_in_table(schedule, planned_datetime, now=now)
            if notification is None:
                continue

            payload = self.node_4_make_text_json_for_webdash(schedule, planned_datetime, notification, now=now)
            payloads.append(payload)
            _speak_async(notification.message)

        return payloads

    def run_forever(self, callback=None) -> None:
        """Repeat the pipeline every 10 minutes while the server is on."""
        self._stop_event.clear()
        while not self._stop_event.is_set():
            payloads = self.run_once()
            if callback is not None:
                callback(payloads)
            self._stop_event.wait(MONITOR_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop_event.set()

    @staticmethod
    def payloads_to_json(payloads: List[Dict[str, object]]) -> str:
        return json.dumps({"notifications": payloads}, indent=2, ensure_ascii=False)


__all__ = [
    "MedicationAssistant",
    "MedicationSchedulerAgent",
    "MONITOR_INTERVAL_SECONDS",
    "ANNOUNCEMENT_WINDOW_MINUTES",
]
