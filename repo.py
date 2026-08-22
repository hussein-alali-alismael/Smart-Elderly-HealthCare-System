import os
from datetime import date, datetime

import pymysql
from flask import jsonify

db_connection = None
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
    )
    
def get_db_connection():
    global db_connection

    if db_connection is not None:
        try:
            db_connection.ping()
            return db_connection
        except Exception:
            db_connection = None

    try:
        db_connection = connect_to_database()
        return db_connection
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


def calculate_date_of_birth(age):
    if not isinstance(age, int):
        return None
    try:
        return date.today().replace(year=date.today().year - age).isoformat()
    except ValueError:
        return None

def list_residents():
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, name, dateOfBirth, notes, createdAt
                FROM elderly_residents
                ORDER BY id ASC
                """
            )
            residents = cursor.fetchall()
        return jsonify({"residents": residents})
    
def create_patient(payload):
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

        user_id = get_default_user_id(connection)
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

def alerts():
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.id, n.residentId, n.type, n.message, n.isSent, n.sentAt,
                       r.name AS resident_name
                FROM notifications n
                LEFT JOIN elderly_residents r ON r.id = n.residentId
                ORDER BY n.id DESC
                """
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


def list_notifications():
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.id, n.residentId, n.type, n.message, n.isSent, n.sentAt,
                       n.isRead, n.readAt, r.name AS resident_name
                FROM notifications n
                LEFT JOIN elderly_residents r ON r.id = n.residentId
                ORDER BY n.id DESC
                """
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


def create_notification(payload):
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
            cursor.execute(
                """
                SELECT id
                FROM notifications
                WHERE residentId = %s
                  AND type = %s
                  AND message = %s
                LIMIT 1
                """,
                (resident_id, notification_type, message),
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


def list_medications():
        connection = get_db_connection()
        if connection is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, dosage, form, manufacturer, sideEffects, instructions, contraindications
                    FROM medications
                    ORDER BY id ASC
                    """
                )
                medications = cursor.fetchall()
            return jsonify({"medications": medications})

        return jsonify({"medications": []})


def create_medication(payload):
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
                INSERT INTO medications (name, dosage, form, manufacturer, sideEffects, instructions, contraindications)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
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


def update_medication(medication_id, payload):
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
            cursor.execute("SELECT id FROM medications WHERE id = %s", (medication_id,))
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


def list_medication_schedules():
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
                LEFT JOIN elderly_residents r ON r.id = ms.residentId
                LEFT JOIN medications m ON m.id = ms.medicationId
                ORDER BY ms.id ASC
                """
            )
            schedules = cursor.fetchall()
        return jsonify({"schedules": schedules})


def list_medication_schedule_times():
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, scheduleId, timeOfDay, createdAt
                FROM medication_schedule_times
                ORDER BY id ASC
                """
            )
            schedule_times = cursor.fetchall()
        return jsonify({"schedule_times": schedule_times})


def list_medication_intakes():
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database is not available."}), 503

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, medicationScheduleTimeId, plannedIntakeDateTime, actualIntakeDateTime,
                       status, actualDosage, notes, createdAt
                FROM medication_intakes
                ORDER BY id ASC
                """
            )
            intakes = cursor.fetchall()
        return jsonify({"intakes": intakes})


def list_resident_medical_conditions():
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
                ORDER BY ermc.residentId ASC, ermc.conditionId ASC
                """
            )
            resident_conditions = cursor.fetchall()
        return jsonify({"resident_conditions": resident_conditions})


def set_resident_fingerprint(resident_id, template_b64):
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
            cursor.execute("SELECT id FROM elderly_residents WHERE id = %s", (resident_id,))
            if cursor.fetchone() is None:
                return jsonify({"error": "Resident not found."}), 404

            cursor.execute(
                "UPDATE elderly_residents SET fingerprintTemplate = %s WHERE id = %s",
                (template_bytes, resident_id),
            )
        connection.commit()

        return jsonify({"status": "updated", "resident_id": resident_id}), 200