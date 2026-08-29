import os
import threading
import atexit
import logging
import hmac
import secrets
import time
from dataclasses import asdict
from datetime import datetime
from typing import cast

from dotenv import load_dotenv
from flask import Flask, current_app, jsonify, redirect, render_template, request, send_from_directory, session
from flask_wtf.csrf import CSRFProtect, generate_csrf

from repo import (
    alerts as repo_alerts,
    create_notification as repo_create_notification,
    create_medication as repo_create_medication,
    create_patient as repo_create_patient,
    create_user as repo_create_user,
    create_medication_schedule as repo_create_medication_schedule,
    create_schedule_time as repo_create_schedule_time,
    create_contact as repo_create_contact,
    create_reference_item as repo_create_reference_item,
    add_resident_relationship as repo_add_resident_relationship,
    get_db_connection,
    get_user_by_open_id,
    ensure_medication_ownership,
    ensure_fingerprint_sensor_mapping,
    list_medication_intakes as repo_list_medication_intakes,
    list_medication_schedules as repo_list_medication_schedules,
    list_medication_schedule_times as repo_list_medication_schedule_times,
    list_medications as repo_list_medications,
    list_notifications as repo_list_notifications,
    list_resident_medical_conditions as repo_list_resident_medical_conditions,
    list_residents,
    get_resident as repo_get_resident,
    update_resident as repo_update_resident,
    delete_resident as repo_delete_resident,
    get_medication as repo_get_medication,
    delete_medication as repo_delete_medication,
    get_medication_schedule as repo_get_medication_schedule,
    update_medication_schedule as repo_update_medication_schedule,
    delete_medication_schedule as repo_delete_medication_schedule,
    list_schedule_times_for_schedule as repo_list_schedule_times_for_schedule,
    update_schedule_time as repo_update_schedule_time,
    delete_schedule_time as repo_delete_schedule_time,
    get_intake as repo_get_intake,
    update_intake as repo_update_intake,
    get_notification as repo_get_notification,
    set_notification_read as repo_set_notification_read,
    delete_notification as repo_delete_notification,
    list_contacts as repo_list_contacts,
    update_contact as repo_update_contact,
    delete_contact as repo_delete_contact,
    list_reference_items as repo_list_reference_items,
    update_reference_item as repo_update_reference_item,
    delete_reference_item as repo_delete_reference_item,
    list_resident_relationships as repo_list_resident_relationships,
    delete_resident_relationship as repo_delete_resident_relationship,
    list_fall_incidents as repo_list_fall_incidents,
    get_fall_incident as repo_get_fall_incident,
    update_fall_incident as repo_update_fall_incident,
    update_medication as repo_update_medication,
    set_resident_fingerprint,
)
from ai_agent import MONITOR_INTERVAL_SECONDS, MedicationSchedulerAgent
from fall_alert_agent import FallDetectionPipeline
from fingerprint_agent import FingerprintMedicationAgent

# Clone-safe config: copy .env.example to .env on a fresh machine before running the app.
# This keeps the project runnable without a pre-existing local secret file.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
if not os.path.exists(os.path.join(os.path.dirname(__file__), ".env")):
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env.example"))

# Default network binding so `flask run` and direct execution are LAN-reachable by default.
os.environ.setdefault("FLASK_RUN_HOST", "0.0.0.0")
os.environ.setdefault("FLASK_RUN_PORT", "5000")

app = None
csrf = CSRFProtect()
_notification_worker_thread = None
_notification_worker_stop = threading.Event()
_notification_worker_state = {
    "running": False,
    "last_run_at": None,
    "last_payload_count": 0,
    "last_error": None,
}
_rate_limit_lock = threading.Lock()
_rate_limit_buckets = {}


def _allow_request(bucket, limit, window_seconds):
    """Apply a small process-local rate limit to sensitive endpoints."""
    now = time.monotonic()
    with _rate_limit_lock:
        attempts = [timestamp for timestamp in _rate_limit_buckets.get(bucket, [])
                    if now - timestamp < window_seconds]
        if len(attempts) >= limit:
            _rate_limit_buckets[bucket] = attempts
            return False
        attempts.append(now)
        _rate_limit_buckets[bucket] = attempts
        return True


def _client_bucket(prefix):
    return f"{prefix}:{request.remote_addr or 'unknown'}"


def _frontend_origins():
    return {
        origin.strip().rstrip("/")
        for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
        if origin.strip()
    }


def _has_valid_fingerprint_device_token():
    device_token = os.getenv("FINGERPRINT_DEVICE_TOKEN", "").strip()
    if not device_token or device_token.startswith("replace-with-"):
        return False
    supplied_token = request.headers.get("X-Fingerprint-Token", "")
    return bool(supplied_token) and hmac.compare_digest(supplied_token, device_token)


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

    _notification_worker_state["running"] = False


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
    thread = _notification_worker_thread
    status = dict(_notification_worker_state)
    status["running"] = bool(
        status["running"] and thread is not None and thread.is_alive()
    )
    return jsonify({"notification_worker": status})


def _login_required(view):
    """Require a logged-in session for browser/API data routes."""
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped


def _admin_required(view):
    """Require an authenticated administrator for reference-data changes."""
    from functools import wraps

    @wraps(view)
    @_login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Administrator access required."}), 403
        return view(*args, **kwargs)

    return wrapped

def create_app():
    global app
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    configured_secret = os.getenv("FLASK_SECRET_KEY", "").strip()
    if not configured_secret or configured_secret.startswith("replace-with-"):
        configured_secret = secrets.token_hex(32)
    app.secret_key = configured_secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Strict")
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
    app.config["WTF_CSRF_TIME_LIMIT"] = None
    app.config["WTF_CSRF_CHECK_DEFAULT"] = False
    csrf.init_app(app)

    @app.after_request
    def add_security_headers(response):
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin and origin in _frontend_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers.add("Vary", "Origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.before_request
    def reject_cross_origin_state_changes():
        """Reject browser cross-site writes before they reach session APIs."""
        if request.method == "OPTIONS":
            origin = request.headers.get("Origin", "").rstrip("/")
            if origin and origin not in _frontend_origins():
                return jsonify({"error": "Cross-origin request rejected."}), 403
            return "", 204
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if request.path.startswith("/api/residents/") and request.path.endswith("/fingerprint") and _has_valid_fingerprint_device_token():
            return None
        if not request.path.startswith("/api/") or request.path in {
            "/api/fingerprint-checkin", "/api/fall-alerts",
            "/api/auth/login", "/api/auth/signup", "/api/auth/logout", "/api/csrf-token"
        }:
            return None

        origin = request.headers.get("Origin")
        if origin:
            allowed = _frontend_origins() | {request.host_url.rstrip("/")}
            if origin.rstrip("/") not in allowed:
                return jsonify({"error": "Cross-origin request rejected."}), 403

        same_origin = (origin is None) or (origin.rstrip("/") == request.host_url.rstrip("/"))
        if same_origin and session.get("user_id") is not None:
            return None

        supplied_token = request.headers.get("X-CSRFToken", "")
        session_csrf_token = session.get("csrf_token")
        if not supplied_token or not session_csrf_token or not hmac.compare_digest(supplied_token, session_csrf_token):
            return jsonify({"error": "CSRF token required."}), 403
        return None
    get_db_connection()
    ensure_medication_ownership()
    ensure_fingerprint_sensor_mapping()

    @app.route("/")
    def index():
        if "user_id" not in session:
            return redirect("/login")
        return render_template("index.html")

    @app.route("/login")
    def login_page():
        # Login is rendered by the React app. The API still decides whether
        # the submitted identity is valid and sets the Flask session cookie.
        return render_template("login.html", csrf_token=generate_csrf())

    @app.route("/signup")
    def signup_page():
        return render_template("signup.html", csrf_token=generate_csrf())

    @app.route("/assets/<path:filename>")
    def react_asset(filename):
        """Serve Vite build assets while keeping them outside the templates folder."""
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        return send_from_directory(static_dir, filename)

    @app.route("/<page>.html")
    def frontend_page(page):
        """Serve individual dashboard pages with authentication."""
        if "user_id" not in session:
            return redirect("/login")
        allowed_pages = {"index", "live", "medications", "notifications", "patient_details"}
        if page not in allowed_pages:
            return jsonify({"error": "Page not found."}), 404
        return render_template(f"{page}.html", csrf_token=generate_csrf())

    @app.route("/<path:frontend_path>")
    def react_frontend_route(frontend_path):
        """Serve the React shell for client-side routes such as /dashboard."""
        if frontend_path.startswith("api/"):
            return jsonify({"error": "API route not found."}), 404
        return render_template("index.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/csrf-token", methods=["GET"])
    @csrf.exempt
    def csrf_token():
        """Return the CSRF token stored in the Flask session.

        Flask-WTF keeps the CSRF token inside the session, not as a separate
        browser cookie. The frontend should send this value in the
        X-CSRFToken header on authenticated write requests.
        """
        token = generate_csrf()
        session["csrf_token"] = token
        return jsonify({"csrf_token": token})

    @app.route("/api/auth/login", methods=["POST"])
    @csrf.exempt
    def login():
        if not _allow_request(_client_bucket("login"), 5, 300):
            return jsonify({"error": "Too many login attempts. Try again later."}), 429
        payload = request.get_json(silent=True) or {}
        if os.getenv("AUTH_ALLOW_LEGACY_IDENTITY", "0").lower() not in {"1", "true", "yes", "on"}:
            return jsonify({
                "error": "Verified OAuth/OIDC authentication is required; legacy identity login is disabled."
            }), 503
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
    @csrf.exempt
    def signup():
        if not _allow_request(_client_bucket("signup"), 3, 900):
            return jsonify({"error": "Too many signup attempts. Try again later."}), 429
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
    @csrf.exempt
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

    @app.route("/api/patients/<int:patient_id>", methods=["GET", "PATCH", "PUT", "DELETE"])
    @_login_required
    def patient_detail(patient_id):
        if request.method == "GET":
            return repo_get_resident(patient_id, session["user_id"])
        if request.method == "DELETE":
            return repo_delete_resident(patient_id, session["user_id"])
        return repo_update_resident(patient_id, request.get_json(silent=True) or {}, session["user_id"])
        
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
        return repo_list_resident_medical_conditions(session["user_id"])

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

    @app.route("/api/residents/<int:resident_id>", methods=["GET", "PATCH", "PUT", "DELETE"])
    @_login_required
    def resident_crud(resident_id):
        if request.method == "GET":
            return repo_get_resident(resident_id, session["user_id"])
        if request.method == "DELETE":
            return repo_delete_resident(resident_id, session["user_id"])
        return repo_update_resident(resident_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/residents", methods=["POST"])
    @_login_required
    def create_resident():
        return repo_create_patient(request.get_json(silent=True) or {}, user_id=session["user_id"])

    @app.route("/api/medications/<int:medication_id>", methods=["GET", "DELETE"])
    @_login_required
    def medication_detail(medication_id):
        if request.method == "GET":
            return repo_get_medication(medication_id, session["user_id"])
        return repo_delete_medication(medication_id, session["user_id"])

    @app.route("/api/medication-schedules", methods=["POST"])
    @_login_required
    def create_schedule():
        return repo_create_medication_schedule(request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/medication-schedules/<int:schedule_id>", methods=["GET", "PATCH", "PUT", "DELETE"])
    @_login_required
    def schedule_detail(schedule_id):
        if request.method == "GET":
            return repo_get_medication_schedule(schedule_id, session["user_id"])
        if request.method == "DELETE":
            return repo_delete_medication_schedule(schedule_id, session["user_id"])
        return repo_update_medication_schedule(schedule_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/medication-schedules/<int:schedule_id>/times", methods=["GET", "POST"])
    @_login_required
    def schedule_times_collection(schedule_id):
        if request.method == "GET":
            return repo_list_schedule_times_for_schedule(schedule_id, session["user_id"])
        return repo_create_schedule_time(schedule_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/medication-schedule-times/<int:time_id>", methods=["PATCH", "PUT", "DELETE"])
    @_login_required
    def schedule_time_detail(time_id):
        if request.method == "DELETE":
            return repo_delete_schedule_time(time_id, session["user_id"])
        return repo_update_schedule_time(time_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/medication-intakes/<int:intake_id>", methods=["GET", "PATCH", "PUT"])
    @_login_required
    def intake_detail(intake_id):
        if request.method == "GET":
            return repo_get_intake(intake_id, session["user_id"])
        return repo_update_intake(intake_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/notifications/<int:notification_id>", methods=["GET", "DELETE"])
    @_login_required
    def notification_detail(notification_id):
        if request.method == "GET":
            return repo_get_notification(notification_id, session["user_id"])
        return repo_delete_notification(notification_id, session["user_id"])

    @app.route("/api/notifications/<int:notification_id>/read", methods=["PATCH"])
    @_login_required
    def notification_read(notification_id):
        return repo_set_notification_read(notification_id, session["user_id"], True)

    @app.route("/api/notifications/<int:notification_id>/unread", methods=["PATCH"])
    @_login_required
    def notification_unread(notification_id):
        return repo_set_notification_read(notification_id, session["user_id"], False)

    @app.route("/api/residents/<int:resident_id>/contacts", methods=["GET", "POST"])
    @_login_required
    def resident_contacts(resident_id):
        if request.method == "GET":
            return repo_list_contacts(resident_id, session["user_id"])
        return repo_create_contact(resident_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/contacts/<int:contact_id>", methods=["PATCH", "PUT", "DELETE"])
    @_login_required
    def contact_detail(contact_id):
        if request.method == "DELETE":
            return repo_delete_contact(contact_id, session["user_id"])
        return repo_update_contact(contact_id, request.get_json(silent=True) or {}, session["user_id"])

    @app.route("/api/residents/<int:resident_id>/<kind>", methods=["GET", "POST"])
    @_login_required
    def resident_relationships(resident_id, kind):
        if kind not in {"conditions", "allergies"}:
            return jsonify({"error": "Relationship type not found."}), 404
        if request.method == "GET":
            return repo_list_resident_relationships(resident_id, session["user_id"], kind)
        return repo_add_resident_relationship(resident_id, request.get_json(silent=True) or {}, session["user_id"], kind)

    @app.route("/api/residents/<int:resident_id>/<kind>/<int:reference_id>", methods=["DELETE"])
    @_login_required
    def resident_relationship_detail(resident_id, kind, reference_id):
        if kind not in {"conditions", "allergies"}:
            return jsonify({"error": "Relationship type not found."}), 404
        return repo_delete_resident_relationship(resident_id, reference_id, session["user_id"], kind)

    @app.route("/api/medical-conditions", methods=["GET", "POST"])
    @_login_required
    def medical_conditions_crud():
        if request.method == "GET":
            return repo_list_reference_items("medical_conditions")
        if session.get("role") != "admin":
            return jsonify({"error": "Administrator access required."}), 403
        return repo_create_reference_item("medical_conditions", request.get_json(silent=True) or {})

    @app.route("/api/medical-conditions/<int:item_id>", methods=["PATCH", "PUT", "DELETE"])
    @_admin_required
    def medical_condition_detail(item_id):
        if request.method == "DELETE":
            return repo_delete_reference_item("medical_conditions", item_id)
        return repo_update_reference_item("medical_conditions", item_id, request.get_json(silent=True) or {})

    @app.route("/api/allergies", methods=["GET", "POST"])
    @_login_required
    def allergies_crud():
        if request.method == "GET":
            return repo_list_reference_items("allergies")
        if session.get("role") != "admin":
            return jsonify({"error": "Administrator access required."}), 403
        return repo_create_reference_item("allergies", request.get_json(silent=True) or {})

    @app.route("/api/allergies/<int:item_id>", methods=["PATCH", "PUT", "DELETE"])
    @_admin_required
    def allergy_detail(item_id):
        if request.method == "DELETE":
            return repo_delete_reference_item("allergies", item_id)
        return repo_update_reference_item("allergies", item_id, request.get_json(silent=True) or {})

    @app.route("/api/fall-incidents", methods=["GET"])
    @_login_required
    def fall_incidents():
        return repo_list_fall_incidents(session["user_id"], session.get("role") == "admin")

    @app.route("/api/fall-incidents/<int:incident_id>", methods=["GET", "PATCH", "PUT"])
    @_login_required
    def fall_incident_detail(incident_id):
        if request.method == "GET":
            return repo_get_fall_incident(incident_id, session["user_id"], session.get("role") == "admin")
        return repo_update_fall_incident(incident_id, request.get_json(silent=True) or {}, session["user_id"], session.get("role") == "admin")

    @app.route("/api/notification-worker/status", methods=["GET"])
    @_login_required
    def notification_worker_status():
        return get_notification_worker_status()

    @app.route("/api/fingerprint-checkin", methods=["POST"])
    @csrf.exempt
    def fingerprint_checkin():
        """Accept a fingerprint payload from a Pi or sensor and run the fingerprint agent.

        Expected JSON body: any of the formats supported by `FingerprintMedicationAgent.process_fingerprint`,
        for example: { "fingerprint_id": 7 } or { "fingerprintTemplate": "...base64..." }
        """
        device_token = os.getenv("FINGERPRINT_DEVICE_TOKEN", "").strip()
        supplied_token = request.headers.get("X-Fingerprint-Token", "")
        if not device_token or device_token.startswith("replace-with-"):
            return jsonify({"error": "Fingerprint device authentication is not configured."}), 503
        if not supplied_token or not hmac.compare_digest(supplied_token, device_token):
            return jsonify({"error": "Fingerprint device authentication required."}), 401

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "Invalid or missing JSON payload."}), 400

        if isinstance(payload, dict):
            normalized = dict(payload)
            resident_id = None
            for key in ("resident_id", "residentId"):
                if key in normalized and normalized[key] is not None:
                    resident_id = normalized[key]
                    break
            if resident_id is None:
                sensor_slot = None
                for key in ("fingerprintSensorSlot", "sensor_position", "sensorPosition"):
                    if key in normalized and normalized[key] is not None:
                        sensor_slot = normalized[key]
                        break
                if sensor_slot is not None:
                    resident_id = sensor_slot
            if resident_id is None:
                for key in ("fingerprint_id", "fingerprintId"):
                    if key in normalized and normalized[key] is not None:
                        resident_id = normalized[key]
                        break
            if resident_id is not None:
                normalized = {"resident_id": resident_id, **{k: v for k, v in normalized.items() if k not in {"resident_id", "residentId", "fingerprint_id", "fingerprintId"}}}
                payload = normalized

        agent = FingerprintMedicationAgent()
        try:
            result = agent.process_fingerprint(payload)
        except Exception as exc:
            logging.exception("Fingerprint agent failed")
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify(result)

    @app.route("/api/fall-alerts", methods=["POST"])
    @csrf.exempt
    def fall_alert():
        """Receive a fall event from a detector and persist it once.

        This endpoint deliberately does not call ``process_fall_event``: that
        method dispatches live webhooks and would post back to this endpoint.
        The HTTP receiver only parses, validates, and stores the event.
        """
        device_token = os.getenv("FALL_ALERT_DEVICE_TOKEN", "").strip()
        supplied_token = request.headers.get("X-Fall-Alert-Token", "")
        if not device_token or device_token.startswith("replace-with-"):
            return jsonify({"error": "Fall-alert device authentication is not configured."}), 503
        if not supplied_token or not hmac.compare_digest(supplied_token, device_token):
            return jsonify({"error": "Fall-alert device authentication required."}), 401
        if not _allow_request(_client_bucket("fall-alert"), 30, 60):
            return jsonify({"error": "Too many fall alerts. Try again later."}), 429

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid or missing JSON payload."}), 400

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        data = cast(dict[str, object], data)
        pipeline = FallDetectionPipeline(backend_url="")
        event = pipeline.node_1_receive_signal(data)
        if event is None:
            return jsonify({"status": "rejected", "reason": "invalid_payload"}), 400
        if not pipeline.node_2_verify_criticality(event):
            db_synced = pipeline.node_3_push_emergency_to_db(event, create_notification=False)
            return jsonify({
                "status": "logged",
                "db_synced": db_synced,
                "event_details": asdict(event),
            }), 201
        if not pipeline.node_3_push_emergency_to_db(event):
            return jsonify({"status": "failed", "reason": "database_unavailable"}), 503
        audio_alerted = pipeline.node_5_trigger_audio_alarm(event)

        return jsonify({
            "status": "received",
            "audio_alerted": audio_alerted,
            "event_details": asdict(event),
        }), 201

    if os.getenv("ENABLE_DEBUG_ROUTES", "").lower() in {"1", "true", "yes", "on"}:
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
    @csrf.exempt
    def enroll_resident_fingerprint(resident_id):
        """Enroll a base64-encoded fingerprint template for a resident.

        Expects JSON: { "fingerprintTemplate": "<base64>" }
        """
        if "user_id" not in session and not _has_valid_fingerprint_device_token():
            return jsonify({"error": "Fingerprint device authentication required."}), 401

        payload = request.get_json(silent=True) or {}
        template_b64 = payload.get("fingerprintTemplate") or payload.get("template")
        if not template_b64:
            return jsonify({"error": "fingerprintTemplate (base64) is required"}), 400

        sensor_position = payload.get("sensor_position")
        if sensor_position is None:
            sensor_position = payload.get("sensorPosition")
        if sensor_position is None:
            sensor_position = payload.get("fingerprintSensorSlot")

        user_id = session.get("user_id")
        return set_resident_fingerprint(resident_id, template_b64, user_id, sensor_position=sensor_position)

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
