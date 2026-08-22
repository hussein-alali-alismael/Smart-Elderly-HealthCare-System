import os
import threading
import atexit
import logging
from datetime import datetime

from flask import Flask, current_app, jsonify, render_template, request

from repo import (
    alerts as repo_alerts,
    create_notification as repo_create_notification,
    create_medication as repo_create_medication,
    create_patient as repo_create_patient,
    get_db_connection,
    list_medication_intakes as repo_list_medication_intakes,
    list_medication_schedules as repo_list_medication_schedules,
    list_medication_schedule_times as repo_list_medication_schedule_times,
    list_medications as repo_list_medications,
    list_notifications as repo_list_notifications,
    list_resident_medical_conditions as repo_list_resident_medical_conditions,
    list_residents,
    update_medication as repo_update_medication,
    set_resident_fingerprint,
)
from ai_agent import MONITOR_INTERVAL_SECONDS, MedicationSchedulerAgent
from fingerprint_agent import FingerprintMedicationAgent

# Default network binding so `flask run` and direct execution are LAN-reachable by default.
os.environ.setdefault("FLASK_RUN_HOST", "0.0.0.0")
os.environ.setdefault("FLASK_RUN_PORT", "5000")

app = None
_notification_worker_thread = None
_notification_worker_stop = threading.Event()
_notification_worker_state = {
    "running": False,
    "last_run_at": None,
    "last_payload_count": 0,
    "last_error": None,
}


def _notification_worker_loop(app_instance):
    scheduler = MedicationSchedulerAgent()
    app_instance.logger.info("Notification worker started with %s second interval.", MONITOR_INTERVAL_SECONDS)

    while not _notification_worker_stop.is_set():
        try:
            payloads = scheduler.run_once()
            _notification_worker_state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
            _notification_worker_state["last_payload_count"] = len(payloads)
            _notification_worker_state["last_error"] = None
            if payloads:
                app_instance.logger.info("Notification worker stored %s reminder(s).", len(payloads))
        except Exception as exc:
            _notification_worker_state["last_error"] = str(exc)
            app_instance.logger.exception("Notification worker cycle failed.")

        _notification_worker_stop.wait(MONITOR_INTERVAL_SECONDS)


def _start_notification_worker(app_instance):
    global _notification_worker_thread

    if os.getenv("DISABLE_NOTIFICATION_WORKER", "").lower() in {"1", "true", "yes", "on"}:
        app_instance.logger.info("Notification worker is disabled by environment variable.")
        return

    if _notification_worker_thread is not None and _notification_worker_thread.is_alive():
        return

    _notification_worker_stop.clear()
    _notification_worker_state["running"] = True
    _notification_worker_thread = threading.Thread(
        target=_notification_worker_loop,
        args=(app_instance,),
        daemon=True,
    )
    _notification_worker_thread.start()


def _stop_notification_worker():
    _notification_worker_state["running"] = False
    _notification_worker_stop.set()


def get_notification_worker_status():
    return jsonify({"notification_worker": _notification_worker_state})

def create_app():
    global app
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    get_db_connection()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/residents", methods=["GET"])
    def list_residents_endpoint():
        return list_residents()

    @app.route("/api/patients", methods=["GET"])
    def list_patients():
        return list_residents()

    @app.route("/api/patients", methods=["POST"])
    def patient_endpoint():
        payload = request.get_json(silent=True) or {}
        return repo_create_patient(payload)
        
    @app.route("/api/alerts")
    def alerts_endpoint():
        return repo_alerts()

    @app.route("/api/notifications", methods=["GET"])
    def list_notifications():
        return repo_list_notifications()

    @app.route("/api/notifications", methods=["POST"])
    def create_notification():
        payload = request.get_json(silent=True) or {}
        return repo_create_notification(payload)

    @app.route("/api/medications", methods=["GET"])
    def list_medications():
        return repo_list_medications()

    @app.route("/api/medication-schedules", methods=["GET"])
    def list_medication_schedules():
        return repo_list_medication_schedules()

    @app.route("/api/medication-schedule-times", methods=["GET"])
    def list_medication_schedule_times():
        return repo_list_medication_schedule_times()

    @app.route("/api/medication-intakes", methods=["GET"])
    def list_medication_intakes():
        return repo_list_medication_intakes()

    @app.route("/api/resident-medical-conditions", methods=["GET"])
    def list_resident_medical_conditions():
        return repo_list_resident_medical_conditions()

    @app.route("/api/medications", methods=["POST"])
    def create_medication():
        payload = request.get_json(silent=True) or {}
        return repo_create_medication(payload)

    @app.route("/api/medications/<int:medication_id>", methods=["PUT", "PATCH"])
    def update_medication(medication_id):
        payload = request.get_json(silent=True) or {}
        return repo_update_medication(medication_id, payload)

    @app.route("/api/notification-worker/status", methods=["GET"])
    def notification_worker_status():
        return get_notification_worker_status()

    @app.route("/api/fingerprint-checkin", methods=["POST"])
    def fingerprint_checkin():
        """Accept a fingerprint payload from a Pi or sensor and run the fingerprint agent.

        Expected JSON body: any of the formats supported by `FingerprintMedicationAgent.process_fingerprint`,
        for example: { "fingerprint_id": 7 } or { "fingerprintTemplate": "...base64..." }
        """
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "Invalid or missing JSON payload."}), 400

        agent = FingerprintMedicationAgent()
        try:
            result = agent.process_fingerprint(payload)
        except Exception as exc:
            logging.exception("Fingerprint agent failed")
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify(result)

    @app.route("/api/_debug/routes", methods=["GET"])
    def debug_list_routes():
        """Return a list of registered routes (for debugging)."""
        routes = []
        for rule in current_app.url_map.iter_rules():
            routes.append({
                "endpoint": rule.endpoint,
                "methods": sorted(list(rule.methods or ())),
                "rule": str(rule),
            })
        return jsonify({"routes": routes})

    @app.route("/api/residents/<int:resident_id>/fingerprint", methods=["POST"])
    def enroll_resident_fingerprint(resident_id):
        """Enroll a base64-encoded fingerprint template for a resident.

        Expects JSON: { "fingerprintTemplate": "<base64>" }
        """
        payload = request.get_json(silent=True) or {}
        template_b64 = payload.get("fingerprintTemplate") or payload.get("template")
        if not template_b64:
            return jsonify({"error": "fingerprintTemplate (base64) is required"}), 400

        # Use repo helper to write the template blob
        return set_resident_fingerprint(resident_id, template_b64)

    if os.getenv("DISABLE_NOTIFICATION_WORKER", "").lower() not in {"1", "true", "yes", "on"} and os.getenv("PYTEST_CURRENT_TEST") is None:
        if os.environ.get("WERKZEUG_RUN_MAIN") in {None, "true"}:
            _start_notification_worker(app)
            atexit.register(_stop_notification_worker)

    return app


app = create_app()


if __name__ == "__main__":
    # Bind to 0.0.0.0 so the server is reachable from other devices on the LAN/hotspot.
    # In production, use a proper WSGI server and firewall rules.
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_RUN_PORT", os.getenv("PORT", "5000"))),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
