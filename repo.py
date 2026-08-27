import os
import threading
from datetime import date, datetime, timedelta

import pymysql
from flask import jsonify

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
        if cursor.fetchone()["count"] == 0:
            cursor.execute("ALTER TABLE medications ADD COLUMN user_id INT NULL AFTER id")
            default_user_id = get_default_user_id(connection)
            if default_user_id is not None:
                cursor.execute("UPDATE medications SET user_id = %s WHERE user_id IS NULL", (default_user_id,))
            cursor.execute("CREATE INDEX idx_medications_user_id ON medications (user_id)")
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
            SELECT id, openId, name, email, role
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


def create_user(name, email):
    """Create a local account using the schema's existing email/openId identity."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name or not email or "@" not in email:
        return jsonify({"error": "Name and a valid email are required."}), 400

    connection = get_db_connection()
    if connection is None:
        return jsonify({"error": "Database is not available."}), 503

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE openId = %s OR email = %s LIMIT 1", (email, email))
        if cursor.fetchone() is not None:
            return jsonify({"error": "An account with this email already exists."}), 409
        cursor.execute(
            "INSERT INTO users (openId, name, email, role) VALUES (%s, %s, %s, 'user')",
            (email, name, email),
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

        if not isinstance(date_of_birth, str):
            return jsonify({"error": "Age must be an integer or dateOfBirth must be a string."}), 400

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

def alerts(user_id=None):
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        sent_date = (
            sent_at.date().isoformat()
            if isinstance(sent_at, datetime)
            else str(sent_at)[:10]
        )
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


def set_resident_fingerprint(resident_id, template_b64, user_id=None):
        """Store a base64-encoded fingerprint template into elderly_residents.fingerprintTemplate.

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

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM elderly_residents WHERE id = %s AND user_id = %s",
                (resident_id, user_id),
            )
            if cursor.fetchone() is None:
                return jsonify({"error": "Resident not found."}), 404

            cursor.execute(
                "UPDATE elderly_residents SET fingerprintTemplate = %s WHERE id = %s AND user_id = %s",
                (template_bytes, resident_id, user_id),
            )
        connection.commit()

        return jsonify({"status": "updated", "resident_id": resident_id}), 200