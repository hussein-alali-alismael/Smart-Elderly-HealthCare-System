---
noteId: "f46c1cc09c8711f1b5d5db6d854d0e44"
tags: []

---

# Smart Elderly Health Care System API

## 1. Purpose

This Flask backend provides data and workflows for a Smart Elderly Health Care System. A React frontend can use it to build a caregiver/admin dashboard for:

- Resident management
- Medication reference management
- Medication schedules and adherence history
- Notifications and medication reminders
- Medical-condition display
- Fingerprint-based medication check-in
- Background reminder-worker monitoring

The API currently uses JSON and connects to the MariaDB/MySQL database `elderly_healthcare_v3`.

## 2. Running the API

The Flask server listens on:

- Local browser: `http://127.0.0.1:5000`
- LAN access: `http://<computer-ip>:5000`

The frontend should store the base URL in an environment variable, for example:

- Vite: `VITE_API_BASE_URL=http://127.0.0.1:5000`
- Create React App: `REACT_APP_API_BASE_URL=http://127.0.0.1:5000`

For requests with a JSON body, send:

`Content-Type: application/json`

The backend uses a session cookie for authentication. The login identity must be an `openId` already verified by the application's OAuth provider. A user may own multiple residents; successful login returns both `residents` and their `residentIds`.

## 3. Common response and error rules

### CSRF and cross-origin development

Before any `POST`, `PUT`, `PATCH`, or `DELETE`, request `GET /api/auth/csrf`
with credentials. The response sets a `csrf_token` cookie and returns the same
value as `csrfToken`. Send that value in the `X-CSRFToken` header and include
credentials on every request. The backend allows only origins listed in
`FRONTEND_ORIGINS`.

For local React development, a Vite proxy to Flask is recommended. It keeps
the browser request same-origin while Flask still serves the API and session.
If the frontend calls Flask directly from another machine, add its exact origin
(including port) to `FRONTEND_ORIGINS` and use HTTPS for reliable cross-site
session cookies.

Successful list responses use a named array property:

- Residents: `{ "residents": [] }`
- Notifications: `{ "notifications": [] }`
- Alerts: `{ "alerts": [] }`
- Medications: `{ "medications": [] }`
- Schedules: `{ "schedules": [] }`
- Schedule times: `{ "schedule_times": [] }`
- Intakes: `{ "intakes": [] }`
- Resident conditions: `{ "resident_conditions": [] }`

Error response:

`{ "error": "Human-readable message" }`

Typical status codes:

- `200` successful read/update or duplicate notification
- `201` successful create
- `400` invalid or missing input
- `404` requested medication/resident was not found
- `503` database is unavailable
- `500` unexpected server/database configuration error

Dates use `YYYY-MM-DD`. Datetimes generally use `YYYY-MM-DD HH:MM:SS` or ISO datetime strings. Boolean database flags are returned as `0` or `1`; the React frontend can convert them with `Boolean(value)`.

## 4. Endpoint reference

## 4A. CRUD endpoint summary

All CRUD routes below require the Flask session created by authentication. The
repository layer enforces the logged-in user's ownership for residents and all
resident-owned records. Reference-data writes require an administrator role.

| Entity | Read | Create | Update | Delete/action |
| --- | --- | --- | --- | --- |
| Residents | `GET /api/residents`, `GET /api/residents/{id}` | `POST /api/residents` | `PUT/PATCH /api/residents/{id}` | `DELETE /api/residents/{id}` |
| Medications | `GET /api/medications`, `GET /api/medications/{id}` | `POST /api/medications` | `PUT/PATCH /api/medications/{id}` | `DELETE /api/medications/{id}` |
| Schedules | `GET /api/medication-schedules`, `GET /api/medication-schedules/{id}` | `POST /api/medication-schedules` | `PUT/PATCH /api/medication-schedules/{id}` | `DELETE /api/medication-schedules/{id}` |
| Schedule times | `GET/POST /api/medication-schedules/{id}/times` | same | `PUT/PATCH /api/medication-schedule-times/{id}` | `DELETE /api/medication-schedule-times/{id}` |
| Intakes | `GET /api/medication-intakes`, `GET /api/medication-intakes/{id}` | workflow/worker | `PUT/PATCH /api/medication-intakes/{id}` | — |
| Notifications | `GET /api/notifications`, `GET /api/notifications/{id}` | `POST /api/notifications` | `/read`, `/unread` actions | `DELETE /api/notifications/{id}` |
| Contacts | `GET/POST /api/residents/{id}/contacts` | same | `PUT/PATCH /api/contacts/{id}` | `DELETE /api/contacts/{id}` |
| Conditions/allergies | `GET /api/medical-conditions`, `GET /api/allergies` | admin only | admin only | admin only |
| Resident relationships | `GET/POST /api/residents/{id}/conditions` or `/allergies` | same | — | `DELETE .../{referenceId}` |
| Fall incidents | `GET /api/fall-incidents`, `GET /api/fall-incidents/{id}` | device endpoint | `PUT/PATCH /api/fall-incidents/{id}` | review by status |

### Authentication

#### `POST /api/auth/login`

Request: `{ "openId": "verified-oauth-open-id" }`

Returns the authenticated user, all residents linked through `elderly_residents.user_id`, and a convenient `residentIds` array. The response sets an HTTP-only session cookie.

#### `GET /api/auth/me`

Returns the current user and their current resident list. Requires login.

#### `POST /api/auth/logout`

Clears the current session.

### Health and dashboard

#### `GET /health`

Expected frontend use: API/server health indicator.

Expected response:

`{ "status": "ok" }`

#### `GET /api/notification-worker/status`

Returns the background medication-reminder worker state.

Response:

```json
{
  "notification_worker": {
    "running": true,
    "last_run_at": "2026-08-20T10:30:00",
    "last_payload_count": 2,
    "last_error": null
  }
}
```

Dashboard UI: show a green/yellow/red status badge and the last run time.

### Residents

#### `GET /api/residents`

Returns residents from `elderly_residents`.

Response item fields:

```json
{
  "id": 7,
  "user_id": 1,
  "name": "Ahmed Mohamed",
  "dateOfBirth": "1945-05-15",
  "notes": "Hypertension",
  "createdAt": "2026-05-13 11:09:37"
}
```

#### `GET /api/patients`

Alias of `GET /api/residents`; use `/api/residents` in new React code for consistent naming.

#### `POST /api/patients`

Creates a resident. The backend assigns the first available user as `user_id`.

Request body: `name` and `condition` are required. Send either `age` or `dateOfBirth`.

```json
{
  "name": "Mary James",
  "age": 78,
  "condition": "Hypertension"
}
```

Alternatively:

```json
{
  "name": "Mary James",
  "dateOfBirth": "1948-02-10",
  "condition": "Hypertension"
}
```

Created response (`201`):

```json
{
  "id": 10,
  "name": "Mary James",
  "dateOfBirth": "1948-02-10",
  "age": 78,
  "condition": "Hypertension",
  "status": "stable"
}
```

Frontend window: resident form with name, age/date of birth, and condition; refresh the resident list after success.

### Notifications and alerts

#### `GET /api/notifications`

Returns all notifications joined with the resident name, newest first.

```json
{
  "notifications": [
    {
      "id": 4,
      "residentId": 7,
      "resident_name": "Ahmed Mohamed",
      "type": "medication_reminder",
      "message": "Medication reminder for Ahmed Mohamed: take Metformin at 2026-08-20 10:00.",
      "isSent": 1,
      "sentAt": "2026-08-20 09:55:00",
      "isRead": 0,
      "readAt": null
    }
  ]
}
```

#### `GET /api/alerts`

Legacy/alternate notification shape for alert cards.

```json
{
  "alerts": [
    {
      "id": 4,
      "patient_id": 7,
      "patient_name": "Ahmed Mohamed",
      "type": "medication_reminder",
      "message": "...",
      "is_sent": 1,
      "sent_at": "2026-08-20 09:55:00"
    }
  ]
}
```

Use `/api/notifications` for new pages. Use `/api/alerts` when building a legacy alert widget.

#### `POST /api/notifications`

Creates a notification, or returns the existing matching notification as a duplicate. Duplicate matching uses the same `residentId`, `type`, and `message`.

Request body:

```json
{
  "residentId": 7,
  "type": "manual_alert",
  "message": "Please check the resident's blood pressure.",
  "isSent": 1,
  "sentAt": "2026-08-20 10:00:00",
  "isRead": 0,
  "readAt": null
}
```

`resident_id` is also accepted instead of `residentId`.

Created response: `201` with `status: "created"`. Duplicate response: `200` with `status: "duplicate"`.

Frontend window: notification composer/modal and notification inbox. After creating, reload notifications.

### Medications

#### `GET /api/medications`

Returns the medication reference catalog.

Response item:

```json
{
  "id": 1,
  "name": "Metformin",
  "dosage": "500mg",
  "form": "Tablet",
  "manufacturer": "Pharmaceutical Co.",
  "sideEffects": "Nausea, Diarrhea",
  "instructions": "Take with meals",
  "contraindications": null
}
```

#### `POST /api/medications`

Creates a medication. Only `name` is required. Request field names use snake_case for the write API.

```json
{
  "name": "Paracetamol",
  "dosage": "500mg",
  "form": "Tablet",
  "manufacturer": "Test Pharma",
  "side_effects": "Drowsiness",
  "instructions": "Take after meals",
  "contraindications": "Liver disease"
}
```

Response: `201`, with response fields `sideEffects`, `instructions`, and `contraindications`.

#### `PUT /api/medications/{medicationId}` or `PATCH /api/medications/{medicationId}`

Updates an existing medication. The request uses the same fields as the create endpoint. `name` is required.

Response: `200` with the updated medication and `status: "updated"`.

Frontend window: searchable medication catalog, add-medication modal, and edit-medication drawer/modal.

### Medication schedules and adherence

These are currently read-only API endpoints. The SQL database supports creating schedules, schedule times, and intakes, but Flask write routes for these resources have not yet been added.

#### `GET /api/medication-schedules`

Response item:

```json
{
  "id": 1,
  "residentId": 7,
  "resident_name": "Ahmed Mohamed",
  "medicationId": 1,
  "medication_name": "Metformin",
  "frequency": "twice-daily",
  "startDate": "2026-08-01",
  "endDate": null,
  "isActive": 1,
  "notes": null,
  "createdAt": "2026-08-01 08:00:00"
}
```

#### `GET /api/medication-schedule-times`

Response item:

```json
{
  "id": 1,
  "scheduleId": 1,
  "timeOfDay": "08:00:00",
  "createdAt": "2026-08-01 08:00:00"
}
```

#### `GET /api/medication-intakes`

Returns adherence records.

```json
{
  "id": 1,
  "medicationScheduleTimeId": 1,
  "plannedIntakeDateTime": "2026-08-20 08:00:00",
  "actualIntakeDateTime": "2026-08-20 08:03:00",
  "status": "taken",
  "actualDosage": "500mg",
  "notes": "Confirmed by fingerprint"
}
```

Possible intake statuses from the database: `pending`, `taken`, `missed`, `refused`, `delayed`.

The background medication scheduler creates one `pending` intake for each valid schedule time for the current day. Once the planned time has passed the configured announcement window, an unconfirmed `pending` intake is changed to `missed`. Fingerprint confirmation changes that day's intake to `taken`; confirmed or manually resolved statuses are not overwritten by the scheduler.

Frontend pages:

1. Medication schedule list grouped by resident.
2. Resident medication timeline/calendar.
3. Adherence dashboard with filters for status and date.

### Medical conditions

#### `GET /api/resident-medical-conditions`

Returns resident-condition relationships.

```json
{
  "resident_conditions": [
    {
      "residentId": 7,
      "resident_name": "Ahmed Mohamed",
      "conditionId": 1,
      "condition_name": "Hypertension",
      "createdAt": "2026-08-01 08:00:00"
    }
  ]
}
```

Frontend use: resident profile condition chips and filtering. There is currently no API route for listing all condition options or modifying relationships.

### Fingerprint workflows

#### `POST /api/residents/{residentId}/fingerprint`

Stores a base64-encoded fingerprint template for an existing resident.

Request:

```json
{
  "fingerprintTemplate": "BASE64_ENCODED_TEMPLATE"
}
```

`template` is accepted as an alias. Response (`200`):

```json
{
  "status": "updated",
  "resident_id": 7
}
```

#### `POST /api/fingerprint-checkin`

This endpoint is for the trusted Raspberry Pi client, not anonymous browser/API callers. Every request must include the `X-Fingerprint-Token` header containing the value configured as `FINGERPRINT_DEVICE_TOKEN` on the Flask server. The request must also include the captured `fingerprintTemplate`; a `fingerprint_id`, sensor position, or resident ID by itself is rejected and cannot record an intake.

Runs the complete fingerprint medication workflow:

1. Match the fingerprint to a resident.
2. Find active medication schedule times for today.
3. Select the nearest schedule within the configured announcement window.
4. Insert or update the intake as `taken`.

Accepted request examples:

```json
{
  "fingerprintTemplate": "BASE64_ENCODED_TEMPLATE",
  "sensor_position": 7,
  "accuracy": 80
}
```

Success response shape:

```json
{
  "success": true,
  "step": "final",
  "message": "Medication intake recorded successfully.",
  "resident": {
    "id": 7,
    "name": "Ahmed Mohamed",
    "fingerprintTemplate": null
  },
  "schedule": {
    "schedule_id": 1,
    "resident_id": 7,
    "resident_name": "Ahmed Mohamed",
    "medication_id": 1,
    "medication_name": "Metformin",
    "medication_dosage": "500mg",
    "schedule_time_id": 1,
    "time_of_day": "08:00:00",
    "start_date": "2026-08-01",
    "end_date": null,
    "is_active": 1
  },
  "result": {
    "success": true,
    "message": "Medication intake recorded successfully.",
    "resident_id": 7,
    "resident_name": "Ahmed Mohamed",
    "medication_schedule_time_id": 1,
    "medication_id": 1,
    "medication_name": "Metformin",
    "planned_intake_datetime": "2026-08-20 08:00:00",
    "actual_intake_datetime": "2026-08-20 08:03:00",
    "intake_row_id": 12,
    "status": "taken"
  }
}
```

Failure responses use HTTP `200` with `success: false` for workflow decisions such as unknown fingerprint or no medication scheduled. The frontend should inspect `success`, `step`, and `message`, not only the HTTP status.

#### `POST /api/fall-alerts`

Receives a fall detector event and persists it. The receiver performs parsing, criticality validation, and database storage only; it does not dispatch another webhook, preventing a self-calling loop. A critical event is acknowledged with `201` after it is stored.

For a critical event, the response also includes `audio_alerted`. Set `SEHCS_SERVER_VOICE_ENABLED=true` on the Flask server to enable the spoken emergency announcement.

Possible failure steps:

- `resident_lookup`: fingerprint was not recognized
- `today_schedule_check`: no medication scheduled today
- `nearest_schedule_selection`: no schedule is within the announcement window
- `final`: database/intake operation failed

Frontend window: fingerprint enrollment screen for staff and a check-in kiosk screen with a large success/failure message.

## 5. Recommended React application structure

### Main dashboard

Load in parallel:

- `GET /api/residents`
- `GET /api/notifications`
- `GET /api/medications`
- `GET /api/notification-worker/status`

Show summary cards:

- Total residents
- Unread notifications
- Active medication schedules
- Worker status

### Residents page

Components:

- `ResidentTable`
- `ResidentSearch`
- `AddResidentModal`
- `ResidentDetailsDrawer`
- `FingerprintEnrollmentModal`

Actions:

- List residents with `GET /api/residents`
- Add resident with `POST /api/patients`
- Enroll fingerprint with `POST /api/residents/{id}/fingerprint`

### Notifications page

Components:

- `NotificationTable`
- `NotificationFilters`
- `CreateNotificationModal`
- `NotificationDetailsDrawer`

Refresh notifications after creating one. Poll every 15 seconds if real-time WebSockets are not added.

### Medication page

Components:

- `MedicationTable`
- `MedicationFormModal`
- `MedicationEditDrawer`
- `MedicationSearch`

Clicking a medication can populate the edit form. After POST/PUT, reload the medication list.

### Schedules and adherence page

Use the three read endpoints to build a joined client-side view:

- schedule → schedule times → intake records

Recommended UI:

- Resident selector
- Date range selector
- Status filter
- Calendar/timeline
- Taken/missed/refused summary cards

### Fingerprint kiosk page

The kiosk should:

1. Send the sensor result to `POST /api/fingerprint-checkin`.
2. Display `message` immediately.
3. On success, display the resident and medication from `result`.
4. On failure, display a clear retry instruction based on `step`.

The diagnostic route `/api/_debug/routes` is disabled unless `ENABLE_DEBUG_ROUTES=1` is explicitly configured, and remains login-protected when enabled.

## 6. Frontend API helper recommendation

Create one wrapper instead of calling `fetch` directly in every component:

- Add the base URL once.
- Add JSON headers automatically.
- Parse JSON consistently.
- Throw an error for non-2xx responses.
- Keep `success: false` workflow responses available to the caller because fingerprint decisions may use HTTP 200.

Suggested client methods:

- `getResidents()`
- `createResident(payload)`
- `getNotifications()`
- `createNotification(payload)`
- `getMedications()`
- `createMedication(payload)`
- `updateMedication(id, payload)`
- `getSchedules()`
- `getScheduleTimes()`
- `getMedicationIntakes()`
- `getResidentConditions()`
- `getWorkerStatus()`
- `enrollFingerprint(residentId, template)`
- `fingerprintCheckin(payload)`

## 7. Backend integration notes for the frontend developer

- If React runs on `localhost:5173` or `localhost:3000` while Flask runs on port `5000`, configure a Vite/CRA proxy or enable Flask CORS. CORS is not currently configured in the backend.
- Do not expose database credentials in React. Database credentials belong only in the Flask server environment.
- The current backend has no pagination or filtering query parameters. Implement client-side filtering for the current dataset; add backend pagination later if the dataset grows.
- The backend currently has no explicit API version prefix. Use `/api/...` as the current namespace.
- The current HTML page is a simple reference dashboard. A React app can replace it without changing the API contracts.
- The SQL schema contains caregiver contacts and allergies, but routes for those tables have not been implemented yet.
- Medication schedules, schedule times, and medication intakes currently have GET-only routes. Add write APIs before building full schedule editing forms.
- The `/api/_debug/routes` endpoint is for development only and should be disabled or protected in production.
