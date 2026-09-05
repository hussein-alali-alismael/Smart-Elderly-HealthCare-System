import os
import threading
from datetime import date, datetime, timedelta

import pymysql
from flask import jsonify
from werkzeug.security import check_password_hash, generate_password_hash

db_connection = None
_db_connections = threading.local()
app = None

def connect_to_database():
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    database = os.getenv("DB_NAME", "elderly_healthcare_v3")
    password = os.getenv("DB_PASSWORD", "")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        # The worker reuses this connection for hours.  With PyMySQL's
        # default autocommit=False, the first SELECT would keep an InnoDB
        # REPEATABLE READ snapshot open until an explicit commit/rollback.
        # Autocommit gives every statement its own transaction, so later
        # worker cycles see schedules added by the web application.
        autocommit=True,
    )
    
def get_db_connection():
    global db_connection

    connection = getattr(_db_connections, "connection", None)
    if connection is not None:
        try:
            connection.ping(reconnect=True)
            return connection
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            _db_connections.connection = None

    try:
        connection = connect_to_database()
        _db_connections.connection = connection
        # Keep this name for compatibility with older imports; request/worker
        # code uses the thread-local connection above.
        db_connection = connection
        return connection
    except Exception as exc:
        if app is not None:
            app.logger.error("Database connection failed: %s", exc)
        # propagate failure so endpoints clearly report the DB is required
        return None
    
def get_default_user_id(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
    return row["id"] if row else None


def ensure_medication_ownership():
    """Add ownership to older installations that used a global medication catalog."""
    connection = get_db_connection()
    if connection is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*) AS count FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'medications'
               AND COLUMN_NAME = 'user_id'"""
        )
        column_count = cursor.fetchone()
        if column_count is not None and column_count["count"] == 0:
            cursor.execute("ALTER TABLE medications ADD COLUMN user_id INT NULL AFTER id")
            default_user_id = get_default_user_id(connection)
            if default_user_id is not None:
                cursor.execute("UPDATE medications SET user_id = %s WHERE user_id IS NULL", (default_user_id,))
            cursor.execute("CREATE INDEX idx_medications_user_id ON medications (user_id)")
    connection.commit()


def ensure_fingerprint_sensor_mapping():
    """Ensure residents store the AS608 sensor slot used for this resident."""
    connection = get_db_connection()
    if connection is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*) AS count FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'elderly_residents'
               AND COLUMN_NAME = 'fingerprintSensorSlot'"""
        )
        column_count = cursor.fetchone()
        if column_count is not None and column_count["count"] == 0:
            cursor.execute(
                "ALTER TABLE elderly_residents ADD COLUMN fingerprintSensorSlot INT NULL AFTER fingerprintTemplate"
            )
            cursor.execute(
                "CREATE INDEX idx_elderly_residents_fingerprint_sensor_slot ON elderly_residents (fingerprintSensorSlot)"
            )
    connection.commit()


def ensure_user_password_column():
    """Add password storage to older installations without changing existing data."""
    connection = get_db_connection()
    if connection is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*) AS count FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'
               AND COLUMN_NAME = 'password_hash'"""
        )
        column_count = cursor.fetchone()
        if column_count is not None and column_count["count"] == 0:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL AFTER email"
            )
    connection.commit()


def ensure_fall_event_id_column():
    """Add the fall-event idempotency key to older database installations."""
    connection = get_db_connection()
    if connection is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*) AS count FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fall_incidents'
               AND COLUMN_NAME = 'evidencePath'"""
        )
        evidence_column = cursor.fetchone()
        if evidence_column is not None and evidence_column["count"] == 0:
            cursor.execute(
                "ALTER TABLE fall_incidents ADD COLUMN evidencePath VARCHAR(500) NULL"
            )
        cursor.execute(
            """SELECT COUNT(*) AS count FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fall_incidents'
               AND COLUMN_NAME = 'eventId'"""
        )
        column_count = cursor.fetchone()
        if column_count is not None and column_count["count"] == 0:
            cursor.execute("ALTER TABLE fall_incidents ADD COLUMN eventId VARCHAR(128) NULL")
            cursor.execute(
                "CREATE UNIQUE INDEX uq_fall_incidents_eventId ON fall_incidents (eventId)"
            )
    connection.commit()


def get_user_by_open_id(open_id):
    """Return the account and all resident IDs associated with an OAuth identity."""
    if not open_id or not isinstance(open_id, str):
        return None

    connection = get_db_connection()
    if connection is None:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, openId, name, email, password_hash, role
            FROM users
            WHERE openId = %s OR email = %s
            LIMIT 1
            """,
            (open_id.strip(), open_id.strip()),
        )
        user = cursor.fetchone()
        if user is None:
            return None

        cursor.execute(
            """
            SELECT id, name, dateOfBirth, notes
            FROM elderly_residents
            WHERE user_id = %s
            ORDER BY id ASC
            """,
            (user["id"],),
        )
        user["residents"] = cursor.fetchall()

    return user


def create_user(name, email, password):
    """Create a local account with a one-way password hash."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""
    if not name or not email or "@" not in email:
        return jsonify({"error": "Name and a valid email are required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    connection = get_db_connection()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE openId = %s OR email = %s LIMIT 1", (email, email))
        if cursor.fetchone() is not None:
            return jsonify({"error": "An account with this email already exists."}), 409
        cursor.execute(
            "INSERT INTO users (openId, name, email, password_hash, role) VALUES (%s, %s, %s, %s, 'user')",
            (email, name, email, generate_password_hash(password)),
        )
        user_id = cursor.lastrowid
    connection.commit()
    return jsonify({"id": user_id, "openId": email, "name": name, "email": email, "role": "user"}), 201


def calculate_date_of_birth(age):
    if not isinstance(age, int):
        return None
    try:
        return date.today().replace(year=date.today().year - age).isoformat()
    except ValueError:
        return None


def validate_elderly_date_of_birth(date_of_birth):
    """Validate that a resident is at least 50 years old today."""
    if not isinstance(date_of_birth, str) or not date_of_birth.strip():
        return False
    try:
        birth_date = datetime.strptime(date_of_birth.strip(), "%Y-%m-%d").date()
    except ValueError:
        return False

    today = date.today()
    try:
        youngest_allowed_birth_date = today.replace(year=today.year - 50)
    except ValueError:
        # A Feb 29 birthday reaches the minimum age on Feb 28 in non-leap years.
        youngest_allowed_birth_date = date(today.year - 50, 2, 28)
    return birth_date <= youngest_allowed_birth_date

def list_residents(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            if user_id is None:
                cursor.execute(
                    """
                    SELECT id, user_id, name, dateOfBirth, notes, createdAt
                    FROM elderly_residents
                    ORDER BY id ASC
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT id, user_id, name, dateOfBirth, notes, createdAt
                    FROM elderly_residents
                    WHERE user_id = %s
                    ORDER BY id ASC
                    """,
                    (user_id,),
                )
            residents = cursor.fetchall()
        return jsonify({"residents": residents})
    
def create_patient(payload, user_id=None):
        name = payload.get("name", "").strip()
        age = payload.get("age")
        date_of_birth = payload.get("dateOfBirth")
        condition = payload.get("condition", "").strip()

        if not name or not condition:
            return jsonify({"error": "Please provide name, age or date of birth, and condition."}), 400

        if date_of_birth is None:
            date_of_birth = calculate_date_of_birth(age)

        if not validate_elderly_date_of_birth(date_of_birth):
            return jsonify({"error": "Resident must be at least 50 years old."}), 400

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        user_id = user_id or get_default_user_id(connection)
        if user_id is None:
            return jsonify({"error": "No user found in the database."}), 500
 
        notes = f"Condition: {condition}"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO elderly_residents (user_id, name, dateOfBirth, notes)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, name, date_of_birth, notes),
            )
            resident_id = cursor.lastrowid
        connection.commit()

        return jsonify({
            "id": resident_id,
            "name": name,
            "dateOfBirth": date_of_birth,
            "age": age,
            "condition": condition,
            "status": "stable",
        }), 201


def get_user_by_credentials(identity, password):
    """Return a user only when the supplied password matches its stored hash."""
    user = get_user_by_open_id(identity)
    if user is None or not user.get("password_hash"):
        return None
    if not check_password_hash(user["password_hash"], password or ""):
        return None
    return user

def alerts(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.id, n.residentId, n.type, n.message, n.isSent, n.sentAt,
                       r.name AS resident_name
                FROM notifications n
                INNER JOIN elderly_residents r ON r.id = n.residentId AND r.user_id = %s
                ORDER BY n.id DESC
                """
                , (user_id,)
            )
            rows = cursor.fetchall()

        alerts = []
        for row in rows:
            alerts.append({
                "id": row["id"],
                "patient_id": row["residentId"],
                "patient_name": row.get("resident_name") or "Unknown",
                "type": row.get("type"),
                "message": row.get("message"),
                "is_sent": row.get("isSent"),
                "sent_at": row.get("sentAt"),
            })
        return jsonify({"alerts": alerts})


def list_notifications(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.id, n.residentId, n.type, n.message, n.isSent, n.sentAt,
                       n.isRead, n.readAt, r.name AS resident_name
                FROM notifications n
                INNER JOIN elderly_residents r ON r.id = n.residentId AND r.user_id = %s
                ORDER BY n.id DESC
                """
                , (user_id,)
            )
            rows = cursor.fetchall()

        notifications = []
        for row in rows:
            notifications.append({
                "id": row["id"],
                "residentId": row["residentId"],
                "resident_name": row.get("resident_name") or "Unknown",
                "type": row.get("type"),
                "message": row.get("message"),
                "isSent": row.get("isSent"),
                "sentAt": row.get("sentAt"),
                "isRead": row.get("isRead"),
                "readAt": row.get("readAt"),
            })

        return jsonify({"notifications": notifications})


def create_notification(payload, user_id=None):
        resident_id = payload.get("residentId") or payload.get("resident_id")
        notification_type = (payload.get("type") or "").strip()
        message = (payload.get("message") or "").strip()
        is_sent = int(payload.get("isSent", 1))
        sent_at = payload.get("sentAt") or datetime.now().isoformat(timespec="seconds")
        is_read = int(payload.get("isRead", 0))
        read_at = payload.get("readAt")

        if resident_id is None or not notification_type or not message:
            return jsonify({"error": "Please provide residentId, type, and message."}), 400

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        sent_date = str(sent_at)[:10]

        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM elderly_residents WHERE id = %s AND user_id = %s", (resident_id, user_id))
            if cursor.fetchone() is None:
                return jsonify({"error": "Resident not found."}), 404
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
                                (resident_id, notification_type, message, sent_date),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return jsonify({
                    "id": existing["id"],
                    "residentId": resident_id,
                    "type": notification_type,
                    "message": message,
                    "isSent": is_sent,
                    "sentAt": sent_at,
                    "isRead": is_read,
                    "readAt": read_at,
                    "status": "duplicate",
                }), 200

            cursor.execute(
                """
                INSERT INTO notifications (residentId, type, message, isSent, sentAt, isRead, readAt)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (resident_id, notification_type, message, is_sent, sent_at, is_read, read_at),
            )
            notification_id = cursor.lastrowid
        connection.commit()

        return jsonify({
            "id": notification_id,
            "residentId": resident_id,
            "type": notification_type,
            "message": message,
            "isSent": is_sent,
            "sentAt": sent_at,
            "isRead": is_read,
            "readAt": read_at,
            "status": "created",
        }), 201


def list_medications(user_id=None):
        connection = get_db_connection()
        if connection is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, dosage, form, manufacturer, sideEffects, instructions, contraindications
                    FROM medications
                    WHERE user_id = %s
                    ORDER BY id ASC
                    """, (user_id,)
                )
                medications = cursor.fetchall()
            return jsonify({"medications": medications})

        return jsonify({"medications": []})


def create_medication(payload, user_id=None):
        name = payload.get("name", "").strip()
        dosage = payload.get("dosage", "").strip()
        form = payload.get("form", "").strip()
        manufacturer = payload.get("manufacturer", "").strip()
        side_effects = payload.get("side_effects", "").strip()
        instructions = payload.get("instructions", "").strip()
        contraindications = payload.get("contraindications", "").strip()

        if not name:
            return jsonify({"error": "Please provide a medication name."}), 400

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO medications (user_id, name, dosage, form, manufacturer, sideEffects, instructions, contraindications)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    name,
                    dosage or None,
                    form or None,
                    manufacturer or None,
                    side_effects or None,
                    instructions or None,
                    contraindications or None,
                ),
            )
            medication_id = cursor.lastrowid
        connection.commit()

        return jsonify({
            "id": medication_id,
            "name": name,
            "dosage": dosage,
            "form": form,
            "manufacturer": manufacturer,
            "sideEffects": side_effects,
            "instructions": instructions,
            "contraindications": contraindications,
            "status": "created",
        }), 201


def update_medication(medication_id, payload, user_id=None):
        name = payload.get("name", "").strip()
        dosage = payload.get("dosage", "").strip()
        form = payload.get("form", "").strip()
        manufacturer = payload.get("manufacturer", "").strip()
        side_effects = payload.get("side_effects", "").strip()
        instructions = payload.get("instructions", "").strip()
        contraindications = payload.get("contraindications", "").strip()

        if not name:
            return jsonify({"error": "Please provide a medication name."}), 400

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM medications WHERE id = %s AND user_id = %s", (medication_id, user_id))
            if cursor.fetchone() is None:
                return jsonify({"error": "Medication not found."}), 404

            cursor.execute(
                """
                UPDATE medications
                SET name = %s,
                    dosage = %s,
                    form = %s,
                    manufacturer = %s,
                    sideEffects = %s,
                    instructions = %s,
                    contraindications = %s
                WHERE id = %s
                """,
                (
                    name,
                    dosage or None,
                    form or None,
                    manufacturer or None,
                    side_effects or None,
                    instructions or None,
                    contraindications or None,
                    medication_id,
                ),
            )
        connection.commit()

        return jsonify({
            "id": medication_id,
            "name": name,
            "dosage": dosage,
            "form": form,
            "manufacturer": manufacturer,
            "sideEffects": side_effects,
            "instructions": instructions,
            "contraindications": contraindications,
            "status": "updated",
        }), 200


def list_medication_schedules(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ms.id, ms.residentId, r.name AS resident_name, ms.medicationId,
                       m.name AS medication_name, ms.frequency, ms.startDate, ms.endDate,
                       ms.isActive, ms.notes, ms.createdAt
                FROM medication_schedules ms
                INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s
                LEFT JOIN medications m ON m.id = ms.medicationId
                ORDER BY ms.id ASC
                """, (user_id,)
            )
            schedules = cursor.fetchall()
        return jsonify({"schedules": schedules})


def list_medication_schedule_times(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT mst.id, mst.scheduleId, mst.timeOfDay, mst.createdAt
                FROM medication_schedule_times mst
                INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId
                INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s
                ORDER BY mst.id ASC
                """, (user_id,)
            )
            schedule_times = cursor.fetchall()
        for schedule_time in schedule_times:
            value = schedule_time.get("timeOfDay")
            if isinstance(value, timedelta):
                total_seconds = int(value.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                schedule_time["timeOfDay"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return jsonify({"schedule_times": schedule_times})


def list_medication_intakes(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                  SELECT mi.id, mi.medicationScheduleTimeId, mi.plannedIntakeDateTime, mi.actualIntakeDateTime,
                      mi.status, mi.actualDosage, mi.notes, mi.createdAt
                FROM medication_intakes mi
                INNER JOIN medication_schedule_times mst ON mst.id = mi.medicationScheduleTimeId
                INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId
                INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s
                ORDER BY mi.id ASC
                """, (user_id,)
            )
            intakes = cursor.fetchall()
        return jsonify({"intakes": intakes})


def list_resident_medical_conditions(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ermc.residentId, r.name AS resident_name, ermc.conditionId,
                       mc.name AS condition_name, ermc.createdAt
                FROM elderly_resident_medical_conditions ermc
                LEFT JOIN elderly_residents r ON r.id = ermc.residentId
                LEFT JOIN medical_conditions mc ON mc.id = ermc.conditionId
                WHERE r.user_id = %s
                ORDER BY ermc.residentId ASC, ermc.conditionId ASC
                """, (user_id,)
            )
            resident_conditions = cursor.fetchall()
        return jsonify({"resident_conditions": resident_conditions})


def set_resident_fingerprint(resident_id, template_b64, user_id=None, sensor_position=None):
        """Store a base64-encoded fingerprint template and sensor slot in the resident row.

        Returns a Flask JSON response.
        """
        if not resident_id:
            return jsonify({"error": "resident_id is required"}), 400

        if not template_b64:
            return jsonify({"error": "fingerprintTemplate (base64) is required"}), 400

        try:
            import base64 as _b64
            template_bytes = _b64.b64decode(template_b64)
        except Exception as exc:
            return jsonify({"error": f"Invalid base64 template: {exc}"}), 400

        sensor_slot = sensor_position if sensor_position is not None else resident_id

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            if user_id is not None:
                cursor.execute(
                    "SELECT id FROM elderly_residents WHERE id = %s AND user_id = %s",
                    (resident_id, user_id),
                )
                if cursor.fetchone() is None:
                    return jsonify({"error": "Resident not found."}), 404

                cursor.execute(
                    "UPDATE elderly_residents SET fingerprintTemplate = %s, fingerprintSensorSlot = %s WHERE id = %s AND user_id = %s",
                    (template_bytes, sensor_slot, resident_id, user_id),
                )
            else:
                cursor.execute(
                    "SELECT id FROM elderly_residents WHERE id = %s",
                    (resident_id,),
                )
                if cursor.fetchone() is None:
                    return jsonify({"error": "Resident not found."}), 404

                cursor.execute(
                    "UPDATE elderly_residents SET fingerprintTemplate = %s, fingerprintSensorSlot = %s WHERE id = %s",
                    (template_bytes, sensor_slot, resident_id),
                )
        connection.commit()

        return jsonify({"status": "updated", "resident_id": resident_id, "sensor_slot": sensor_slot}), 200


# ---------------------------------------------------------------------------
# Authenticated CRUD helpers.  Every function below receives the owner from
# the Flask session; none of these paths falls back to the first database user.
# ---------------------------------------------------------------------------

def _db_or_error():
    connection = get_db_connection()
    return connection or None


def get_resident(resident_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, user_id, name, dateOfBirth, notes, createdAt, updatedAt FROM elderly_residents WHERE id = %s AND user_id = %s", (resident_id, user_id))
        row = cursor.fetchone()
    return (jsonify(row), 200) if row else (jsonify({"error": "Resident not found."}), 404)


def update_resident(resident_id, payload, user_id):
    name = str(payload.get("name", "")).strip()
    date_of_birth = payload.get("dateOfBirth")
    notes = str(payload.get("notes", "")).strip() or None
    if not name:
        return jsonify({"error": "Please provide a resident name."}), 400
    if not validate_elderly_date_of_birth(date_of_birth):
        return jsonify({"error": "Resident must be at least 50 years old."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("UPDATE elderly_residents SET name = %s, dateOfBirth = %s, notes = %s WHERE id = %s AND user_id = %s", (name, date_of_birth, notes, resident_id, user_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Resident not found."}), 404
    connection.commit()
    return get_resident(resident_id, user_id)


def delete_resident(resident_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM elderly_residents WHERE id = %s AND user_id = %s", (resident_id, user_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Resident not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": resident_id})


def get_medication(medication_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, name, dosage, form, manufacturer, sideEffects, instructions, contraindications, createdAt, updatedAt FROM medications WHERE id = %s AND user_id = %s", (medication_id, user_id))
        row = cursor.fetchone()
    return (jsonify(row), 200) if row else (jsonify({"error": "Medication not found."}), 404)


def delete_medication(medication_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM medications WHERE id = %s AND user_id = %s", (medication_id, user_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Medication not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": medication_id})


def create_medication_schedule(payload, user_id):
    resident_id = payload.get("residentId")
    medication_id = payload.get("medicationId")
    frequency = str(payload.get("frequency", "")).strip()
    start_date = payload.get("startDate")
    end_date = payload.get("endDate") or None
    if not resident_id or not medication_id or not frequency or not start_date:
        return jsonify({"error": "residentId, medicationId, frequency, and startDate are required."}), 400
    if end_date and str(start_date) > str(end_date):
        return jsonify({"error": "startDate must not be after endDate."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM elderly_residents WHERE id = %s AND user_id = %s", (resident_id, user_id))
        if cursor.fetchone() is None:
            return jsonify({"error": "Resident not found."}), 404
        cursor.execute("SELECT id FROM medications WHERE id = %s AND user_id = %s", (medication_id, user_id))
        if cursor.fetchone() is None:
            return jsonify({"error": "Medication not found."}), 404
        cursor.execute("INSERT INTO medication_schedules (residentId, medicationId, frequency, startDate, endDate, isActive, notes) VALUES (%s, %s, %s, %s, %s, %s, %s)", (resident_id, medication_id, frequency, start_date, end_date, int(bool(payload.get("isActive", 1))), payload.get("notes")))
        schedule_id = cursor.lastrowid
    connection.commit()
    return get_medication_schedule(schedule_id, user_id, 201)


def get_medication_schedule(schedule_id, user_id, status=200):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT ms.id, ms.residentId, ms.medicationId, ms.frequency, ms.startDate, ms.endDate, ms.isActive, ms.notes, ms.createdAt, ms.updatedAt FROM medication_schedules ms INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s WHERE ms.id = %s", (user_id, schedule_id))
        row = cursor.fetchone()
    return (jsonify(row), status) if row else (jsonify({"error": "Schedule not found."}), 404)


def update_medication_schedule(schedule_id, payload, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    fields = {"frequency": payload.get("frequency"), "startDate": payload.get("startDate"), "endDate": payload.get("endDate") or None, "isActive": int(bool(payload.get("isActive", 1))), "notes": payload.get("notes")}
    if not fields["frequency"] or not fields["startDate"]:
        return jsonify({"error": "frequency and startDate are required."}), 400
    if fields["endDate"] and str(fields["startDate"]) > str(fields["endDate"]):
        return jsonify({"error": "startDate must not be after endDate."}), 400
    with connection.cursor() as cursor:
        cursor.execute("UPDATE medication_schedules ms INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s SET ms.frequency=%s, ms.startDate=%s, ms.endDate=%s, ms.isActive=%s, ms.notes=%s WHERE ms.id=%s", (user_id, fields["frequency"], fields["startDate"], fields["endDate"], fields["isActive"], fields["notes"], schedule_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Schedule not found."}), 404
    connection.commit()
    return get_medication_schedule(schedule_id, user_id)


def delete_medication_schedule(schedule_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("DELETE ms FROM medication_schedules ms INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s WHERE ms.id = %s", (user_id, schedule_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Schedule not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": schedule_id})


def list_schedule_times_for_schedule(schedule_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT mst.id, mst.scheduleId, mst.timeOfDay, mst.createdAt, mst.updatedAt FROM medication_schedule_times mst INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s WHERE mst.scheduleId = %s ORDER BY mst.id", (user_id, schedule_id))
        rows = cursor.fetchall()
    return jsonify({"schedule_times": rows})


def create_schedule_time(schedule_id, payload, user_id):
    time_of_day = payload.get("timeOfDay")
    if not time_of_day:
        return jsonify({"error": "timeOfDay is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT ms.id FROM medication_schedules ms INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s WHERE ms.id = %s", (user_id, schedule_id))
        if cursor.fetchone() is None:
            return jsonify({"error": "Schedule not found."}), 404
        cursor.execute("SELECT id FROM medication_schedule_times WHERE scheduleId = %s AND timeOfDay = %s", (schedule_id, time_of_day))
        if cursor.fetchone() is not None:
            return jsonify({"error": "This schedule time already exists."}), 409
        cursor.execute("INSERT INTO medication_schedule_times (scheduleId, timeOfDay) VALUES (%s, %s)", (schedule_id, time_of_day))
        time_id = cursor.lastrowid
    connection.commit()
    return jsonify({"id": time_id, "scheduleId": schedule_id, "timeOfDay": time_of_day}), 201


def update_schedule_time(time_id, payload, user_id):
    time_of_day = payload.get("timeOfDay")
    if not time_of_day:
        return jsonify({"error": "timeOfDay is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("UPDATE medication_schedule_times mst INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s SET mst.timeOfDay = %s WHERE mst.id = %s", (user_id, time_of_day, time_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Schedule time not found."}), 404
    connection.commit()
    return jsonify({"id": time_id, "timeOfDay": time_of_day, "status": "updated"})


def delete_schedule_time(time_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("DELETE mst FROM medication_schedule_times mst INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s WHERE mst.id = %s", (user_id, time_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Schedule time not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": time_id})


def get_intake(intake_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT mi.* FROM medication_intakes mi INNER JOIN medication_schedule_times mst ON mst.id = mi.medicationScheduleTimeId INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s WHERE mi.id = %s", (user_id, intake_id))
        row = cursor.fetchone()
    return (jsonify(row), 200) if row else (jsonify({"error": "Intake not found."}), 404)


def update_intake(intake_id, payload, user_id):
    status = payload.get("status")
    allowed = {"pending", "taken", "missed", "refused", "delayed"}
    if status not in allowed:
        return jsonify({"error": "Invalid intake status."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    actual = payload.get("actualIntakeDateTime") if status == "taken" else None
    with connection.cursor() as cursor:
        cursor.execute("UPDATE medication_intakes mi INNER JOIN medication_schedule_times mst ON mst.id = mi.medicationScheduleTimeId INNER JOIN medication_schedules ms ON ms.id = mst.scheduleId INNER JOIN elderly_residents r ON r.id = ms.residentId AND r.user_id = %s SET mi.status=%s, mi.actualIntakeDateTime=%s, mi.confirmedByUserAt=CASE WHEN %s='taken' THEN NOW() ELSE NULL END, mi.notes=%s WHERE mi.id=%s", (user_id, status, actual, status, payload.get("notes"), intake_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Intake not found."}), 404
    connection.commit()
    return get_intake(intake_id, user_id)


def get_notification(notification_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT n.* FROM notifications n INNER JOIN elderly_residents r ON r.id = n.residentId AND r.user_id = %s WHERE n.id = %s", (user_id, notification_id))
        row = cursor.fetchone()
    return (jsonify(row), 200) if row else (jsonify({"error": "Notification not found."}), 404)


def set_notification_read(notification_id, user_id, is_read):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("UPDATE notifications n INNER JOIN elderly_residents r ON r.id = n.residentId AND r.user_id = %s SET n.isRead=%s, n.readAt=CASE WHEN %s=1 THEN NOW() ELSE NULL END WHERE n.id=%s", (user_id, int(is_read), int(is_read), notification_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Notification not found."}), 404
    connection.commit()
    return get_notification(notification_id, user_id)


def delete_notification(notification_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("DELETE n FROM notifications n INNER JOIN elderly_residents r ON r.id = n.residentId AND r.user_id = %s WHERE n.id=%s", (user_id, notification_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Notification not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": notification_id})


def list_contacts(resident_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT c.* FROM caregiver_contacts c INNER JOIN elderly_residents r ON r.id=c.residentId AND r.user_id=%s WHERE c.residentId=%s ORDER BY c.id", (user_id, resident_id))
        rows = cursor.fetchall()
    return jsonify({"contacts": rows})


def create_contact(resident_id, payload, user_id):
    name = str(payload.get("contactName", "")).strip()
    if not name:
        return jsonify({"error": "contactName is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM elderly_residents WHERE id=%s AND user_id=%s", (resident_id, user_id))
        if cursor.fetchone() is None:
            return jsonify({"error": "Resident not found."}), 404
        cursor.execute("INSERT INTO caregiver_contacts (residentId, contactName, relationship, email, phoneNumber) VALUES (%s,%s,%s,%s,%s)", (resident_id, name, payload.get("relationship"), payload.get("email"), payload.get("phoneNumber")))
        contact_id = cursor.lastrowid
    connection.commit()
    return jsonify({"id": contact_id, "residentId": resident_id, "contactName": name, "status": "created"}), 201


def update_contact(contact_id, payload, user_id):
    name = str(payload.get("contactName", "")).strip()
    if not name:
        return jsonify({"error": "contactName is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("UPDATE caregiver_contacts c INNER JOIN elderly_residents r ON r.id=c.residentId AND r.user_id=%s SET c.contactName=%s,c.relationship=%s,c.email=%s,c.phoneNumber=%s WHERE c.id=%s", (user_id, name, payload.get("relationship"), payload.get("email"), payload.get("phoneNumber"), contact_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Contact not found."}), 404
    connection.commit()
    return jsonify({"id": contact_id, "contactName": name, "status": "updated"})


def delete_contact(contact_id, user_id):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("DELETE c FROM caregiver_contacts c INNER JOIN elderly_residents r ON r.id=c.residentId AND r.user_id=%s WHERE c.id=%s", (user_id, contact_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Contact not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": contact_id})


def list_reference_items(table):
    if table not in {"medical_conditions", "allergies"}:
        raise ValueError("Invalid reference table")
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT id, name, createdAt, updatedAt FROM {table} ORDER BY name")
        rows = cursor.fetchall()
    return jsonify({table: rows})


def create_reference_item(table, payload):
    if table not in {"medical_conditions", "allergies"}:
        raise ValueError("Invalid reference table")
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {table} (name) VALUES (%s)", (name,))
            item_id = cursor.lastrowid
        connection.commit()
    except pymysql.err.IntegrityError:
        return jsonify({"error": "An item with this name already exists."}), 409
    return jsonify({"id": item_id, "name": name, "status": "created"}), 201


def update_reference_item(table, item_id, payload):
    if table not in {"medical_conditions", "allergies"}:
        raise ValueError("Invalid reference table")
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET name=%s WHERE id=%s", (name, item_id))
            if cursor.rowcount == 0:
                return jsonify({"error": "Reference item not found."}), 404
        connection.commit()
    except pymysql.err.IntegrityError:
        return jsonify({"error": "An item with this name already exists."}), 409
    return jsonify({"id": item_id, "name": name, "status": "updated"})


def delete_reference_item(table, item_id):
    if table not in {"medical_conditions", "allergies"}:
        raise ValueError("Invalid reference table")
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table} WHERE id=%s", (item_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Reference item not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "id": item_id})


def list_resident_relationships(resident_id, user_id, kind):
    config = {
        "conditions": ("elderly_resident_medical_conditions", "medical_conditions", "conditionId", "resident_conditions"),
        "allergies": ("elderly_resident_allergies", "allergies", "allergyId", "resident_allergies"),
    }
    if kind not in config:
        raise ValueError("Invalid relationship type")
    junction, reference, ref_key, output = config[kind]
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT r.id, r.name FROM elderly_residents er INNER JOIN {junction} j ON j.residentId=er.id INNER JOIN {reference} r ON r.id=j.{ref_key} WHERE er.id=%s AND er.user_id=%s ORDER BY r.name", (resident_id, user_id))
        rows = cursor.fetchall()
    return jsonify({output: rows})


def add_resident_relationship(resident_id, payload, user_id, kind):
    config = {"conditions": ("elderly_resident_medical_conditions", "medical_conditions", "conditionId"), "allergies": ("elderly_resident_allergies", "allergies", "allergyId")}
    if kind not in config:
        raise ValueError("Invalid relationship type")
    junction, reference, ref_key = config[kind]
    reference_id = payload.get("conditionId" if kind == "conditions" else "allergyId")
    if not reference_id:
        return jsonify({"error": "A reference item id is required."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM elderly_residents WHERE id=%s AND user_id=%s", (resident_id, user_id))
            if cursor.fetchone() is None:
                return jsonify({"error": "Resident not found."}), 404
            cursor.execute(f"SELECT id FROM {reference} WHERE id=%s", (reference_id,))
            if cursor.fetchone() is None:
                return jsonify({"error": "Reference item not found."}), 404
            cursor.execute(f"INSERT INTO {junction} (residentId, {ref_key}) VALUES (%s,%s)", (resident_id, reference_id))
        connection.commit()
    except pymysql.err.IntegrityError:
        return jsonify({"error": "This relationship already exists."}), 409
    return jsonify({"residentId": resident_id, ref_key: reference_id, "status": "created"}), 201


def delete_resident_relationship(resident_id, reference_id, user_id, kind):
    config = {"conditions": ("elderly_resident_medical_conditions", "conditionId"), "allergies": ("elderly_resident_allergies", "allergyId")}
    if kind not in config:
        raise ValueError("Invalid relationship type")
    junction, ref_key = config[kind]
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE j FROM {junction} j INNER JOIN elderly_residents r ON r.id=j.residentId AND r.user_id=%s WHERE j.residentId=%s AND j.{ref_key}=%s", (user_id, resident_id, reference_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Relationship not found."}), 404
    connection.commit()
    return jsonify({"status": "deleted", "residentId": resident_id, ref_key: reference_id})


def list_fall_incidents(user_id, is_admin=False):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        query = "SELECT fi.* FROM fall_incidents fi LEFT JOIN elderly_residents r ON r.id=fi.residentId WHERE %s=1 OR r.user_id=%s ORDER BY fi.detectedAt DESC"
        cursor.execute(query, (int(is_admin), user_id))
        rows = cursor.fetchall()
    return jsonify({"fall_incidents": rows})


def get_fall_incident(incident_id, user_id, is_admin=False):
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("SELECT fi.* FROM fall_incidents fi LEFT JOIN elderly_residents r ON r.id=fi.residentId WHERE fi.id=%s AND (%s=1 OR r.user_id=%s)", (incident_id, int(is_admin), user_id))
        row = cursor.fetchone()
    return (jsonify(row), 200) if row else (jsonify({"error": "Fall incident not found."}), 404)


def update_fall_incident(incident_id, payload, user_id, is_admin=False):
    status = payload.get("status")
    if status not in {"detected", "confirmed", "false_alarm", "resolved"}:
        return jsonify({"error": "Invalid fall incident status."}), 400
    connection = _db_or_error()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503
    with connection.cursor() as cursor:
        cursor.execute("UPDATE fall_incidents fi LEFT JOIN elderly_residents r ON r.id=fi.residentId SET fi.status=%s, fi.resolutionNotes=%s, fi.resolvedAt=CASE WHEN %s='resolved' THEN NOW() ELSE NULL END WHERE fi.id=%s AND (%s=1 OR r.user_id=%s)", (status, payload.get("resolutionNotes"), status, incident_id, int(is_admin), user_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Fall incident not found."}), 404
    connection.commit()
    return jsonify({"id": incident_id, "status": status, "status_message": "updated"})