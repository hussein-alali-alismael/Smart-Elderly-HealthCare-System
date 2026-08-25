import os
import threading
import atexit
import logging
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, current_app, jsonify, redirect, render_template, request, session

from repo import (
    alerts as repo_alerts,
    create_notification as repo_create_notification,
    create_medication as repo_create_medication,
    create_patient as repo_create_patient,
    create_user as repo_create_user,
    get_db_connection,
    get_user_by_open_id,
    ensure_medication_ownership,
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

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

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


def _login_required(view):
    """Require a logged-in session for browser/API data routes."""
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped

def create_app():
    global app
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "development-only-change-me")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
    get_db_connection()
    ensure_medication_ownership()

    @app.route("/")
    def index():
        if "user_id" not in session:
            return redirect("/login")
        return render_template("index.html")

    @app.route("/login")
    def login_page():
        if "user_id" in session:
            return redirect("/")
        return render_template("login.html")

    @app.route("/signup")
    def signup_page():
        if "user_id" in session:
            return redirect("/")
        return render_template("signup.html")

    @app.route("/<page>.html")
    def frontend_page(page):
        """Render one of the dashboard pages from Flask's templates folder."""
        allowed_pages = {"index", "live", "medications", "notifications", "patient_details"}
        if page not in allowed_pages:
            return jsonify({"error": "Page not found."}), 404
        if "user_id" not in session:
            return redirect("/login")
        return render_template(f"{page}.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        payload = request.get_json(silent=True) or {}
        open_id = payload.get("openId") or payload.get("open_id")
        user = get_user_by_open_id(open_id)
        if user is None:
            return jsonify({"error": "Invalid user identity."}), 401

        session.clear()
        session["user_id"] = user["id"]
        session["open_id"] = user["openId"]
        session["role"] = user["role"]
        return jsonify({
            "user": {
                "id": user["id"],
                "openId": user["openId"],
                "name": user["name"],
                "email": user["email"],
                "role": user["role"],
            },
            "residents": user["residents"],
            "residentIds": [resident["id"] for resident in user["residents"]],
        })

    @app.route("/api/auth/signup", methods=["POST"])
    def signup():
        payload = request.get_json(silent=True) or {}
        result = repo_create_user(payload.get("name"), payload.get("email"))
        if isinstance(result, tuple):
            response, status = result
            if status != 201:
                return response, status
        user = get_user_by_open_id(payload.get("email"))
        if user is None:
            return jsonify({"error": "Account was created but could not be loaded."}), 500
        session.clear()
        session["user_id"] = user["id"]
        session["open_id"] = user["openId"]
        session["role"] = user["role"]
        return jsonify({"user": {key: user[key] for key in ("id", "openId", "name", "email", "role")}}), 201

    @app.route("/api/auth/me", methods=["GET"])
    @_login_required
    def current_user():
        user = get_user_by_open_id(session.get("open_id"))
        if user is None:
            session.clear()
            return jsonify({"error": "User account no longer exists."}), 401
        return jsonify({
            "user": {key: user[key] for key in ("id", "openId", "name", "email", "role")},
            "residents": user["residents"],
            "residentIds": [resident["id"] for resident in user["residents"]],
        })

    @app.route("/api/auth/logout", methods=["POST"])
    def logout():
        session.clear()
        return jsonify({"status": "logged_out"})

    @app.route("/api/residents", methods=["GET"])
    @_login_required
    def list_residents_endpoint():
        return list_residents(session["user_id"])

    @app.route("/api/patients", methods=["GET"])
    @_login_required
    def list_patients():
        return list_residents(session["user_id"])

    @app.route("/api/patients", methods=["POST"])
    @_login_required
    def patient_endpoint():
        payload = request.get_json(silent=True) or {}
        return repo_create_patient(payload, user_id=session["user_id"])
        
    @app.route("/api/alerts")
    @_login_required
    def alerts_endpoint():
        return repo_alerts(session["user_id"])

    @app.route("/api/notifications", methods=["GET"])
    @_login_required
    def list_notifications():
        return repo_list_notifications(session["user_id"])

    @app.route("/api/notifications", methods=["POST"])
    @_login_required
    def create_notification():
        payload = request.get_json(silent=True) or {}
        return repo_create_notification(payload, session["user_id"])

    @app.route("/api/medications", methods=["GET"])
    @_login_required
    def list_medications():
        return repo_list_medications(session["user_id"])

    @app.route("/api/medication-schedules", methods=["GET"])
    @_login_required
    def list_medication_schedules():
        return repo_list_medication_schedules(session["user_id"])

    @app.route("/api/medication-schedule-times", methods=["GET"])
    @_login_required
    def list_medication_schedule_times():
        return repo_list_medication_schedule_times(session["user_id"])

    @app.route("/api/medication-intakes", methods=["GET"])
    @_login_required
    def list_medication_intakes():
        return repo_list_medication_intakes(session["user_id"])

    @app.route("/api/resident-medical-conditions", methods=["GET"])
    @_login_required
    def list_resident_medical_conditions():
        return repo_list_resident_medical_conditions()

    @app.route("/api/medications", methods=["POST"])
    @_login_required
    def create_medication():
        payload = request.get_json(silent=True) or {}
        return repo_create_medication(payload, session["user_id"])

    @app.route("/api/medications/<int:medication_id>", methods=["PUT", "PATCH"])
    @_login_required
    def update_medication(medication_id):
        payload = request.get_json(silent=True) or {}
        return repo_update_medication(medication_id, payload, session["user_id"])

    @app.route("/api/notification-worker/status", methods=["GET"])
    @_login_required
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
    @_login_required
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
    @_login_required
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
