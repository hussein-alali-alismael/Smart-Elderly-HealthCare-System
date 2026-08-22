"""Streamlit frontend for the medication assistant and reminder pipeline."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, cast

import streamlit as st

from ai_agent import MedicationAssistant, MedicationSchedulerAgent

st.set_page_config(page_title="SEHCS AI Agent", page_icon="💊", layout="wide")

FLASK_BASE_URL = os.getenv("FLASK_BASE_URL", "http://127.0.0.1:5000")


@st.cache_resource

def get_chatbot() -> MedicationAssistant:
    return MedicationAssistant()


@st.cache_resource

def get_scheduler() -> MedicationSchedulerAgent:
    return MedicationSchedulerAgent()


if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "last_payloads" not in st.session_state:
    st.session_state.last_payloads = []

chatbot = get_chatbot()
scheduler = get_scheduler()


def _push_notifications_to_dashboard(payloads: List[dict]) -> tuple[int, int]:
    created = 0
    duplicates = 0

    for payload in payloads:
        notification = payload.get("notification", {})
        request = urllib.request.Request(
            f"{FLASK_BASE_URL}/api/notifications",
            data=json.dumps(notification).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
                if result.get("status") == "created":
                    created += 1
                else:
                    duplicates += 1
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Dashboard sync failed: {error.reason}. {error_body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Dashboard sync failed: {error.reason}") from error

    return created, duplicates

st.title("SEHCS AI Medication Agent")
st.caption("Gemini + LangChain + Streamlit with memory, medication reminders, and dashboard JSON output.")

chat_tab, agent_tab, json_tab = st.tabs(["Chat assistant", "Medication agent", "Webdash JSON"])

with chat_tab:
    st.subheader("Local chatbot with memory")
    st.write("Ask questions about schedules, reminders, or the application. The chat remembers this session.")

    for item in st.session_state.chat_messages:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])

    user_prompt = st.chat_input("Type your message here")
    if user_prompt:
        st.session_state.chat_messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            response = chatbot.ask(user_prompt, session_id="streamlit-session")
            st.markdown(response)
        st.session_state.chat_messages.append({"role": "assistant", "content": response})

with agent_tab:
    st.subheader("Medication reminder pipeline")
    st.write("The reminder worker now runs inside the Flask server every 5 minutes and stores notifications automatically.")

    worker_status = None
    try:
        request = urllib.request.Request(f"{FLASK_BASE_URL}/api/notification-worker/status", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            worker_status = json.loads(response.read().decode("utf-8") or "{}")
    except Exception:
        worker_status = None

    if worker_status and isinstance(worker_status.get("notification_worker"), dict):
        status = worker_status["notification_worker"]
        st.metric("Worker running", "Yes" if status.get("running") else "No")
        st.caption(f"Last run: {status.get('last_run_at') or '—'}")
        st.caption(f"Last payload count: {status.get('last_payload_count')}")
        if status.get("last_error"):
            st.error(f"Worker error: {status.get('last_error')}")
    else:
        st.warning("Could not reach the Flask worker status endpoint.")

    schedules = scheduler.node_1_load_schedule_time()
    st.markdown("#### Loaded schedules")
    if schedules:
        st.dataframe([s.__dict__ for s in schedules], use_container_width=True, hide_index=True)
    else:
        st.info("No active schedules were found or the database is unavailable.")

    st.markdown("#### Last generated payloads")
    if st.session_state.last_payloads:
        payload_rows = []
        for payload in st.session_state.last_payloads:
            payload_dict = cast(Dict[str, Any], payload) if isinstance(payload, dict) else {}
            schedule = cast(Dict[str, Any], payload_dict.get("schedule", {})) if isinstance(payload_dict.get("schedule", {}), dict) else {}
            notification = cast(Dict[str, Any], payload_dict.get("notification", {})) if isinstance(payload_dict.get("notification", {}), dict) else {}
            payload_rows.append({
                "resident": schedule.get("resident_name"),
                "medication": schedule.get("medication_name"),
                "planned": payload_dict.get("planned_intake_datetime"),
                "message": notification.get("message"),
            })

        st.dataframe(payload_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("Run a cycle to generate dashboard payloads.")

with json_tab:
    st.subheader("JSON for webdash")
    st.write("Use the button below to push the notification message from the generated JSON into the Flask dashboard.")

    pretty = scheduler.payloads_to_json(st.session_state.last_payloads)
    st.code(pretty, language="json")

    if st.button("Push notifications to dashboard", use_container_width=True, disabled=not st.session_state.last_payloads):
        try:
            created, duplicates = _push_notifications_to_dashboard(st.session_state.last_payloads)
            st.success(f"Synced {created} notification(s) to the dashboard. {duplicates} already existed.")
        except Exception as error:
            st.error(str(error))

    st.download_button(
        "Download JSON",
        data=pretty,
        file_name="webdash_notifications.json",
        mime="application/json",
        use_container_width=True,
    )

st.divider()
st.caption("Tip: set GEMINI_API_KEY in your .env file before chatting with the assistant.")
