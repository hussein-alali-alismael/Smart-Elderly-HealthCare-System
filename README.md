# Smart Elderly Health Care System

A Flask-based backend and Raspberry Pi integration for monitoring elderly residents, managing medications, generating reminders, and confirming medication intake with an AS608 fingerprint sensor.

## Project overview

```text
React frontend / browser
          |
          | HTTP JSON, TCP 5000
          v
Flask API on Windows laptop
          |
          | PyMySQL, TCP 3306
          v
XAMPP MariaDB/MySQL database
          ^
          |
          | HTTP JSON over Wi-Fi/Ethernet, TCP 5000
          |
Raspberry Pi + AS608 fingerprint sensor
```

The Flask server is the only component that talks directly to the database. The Raspberry Pi never needs the XAMPP database password; it only sends fingerprint/check-in requests to the Flask API.

## Repository layout

| Path | Purpose |
| --- | --- |
| `app.py` | Flask application and API route registration |
| `repo.py` | Database connection and database-backed repository functions |
| `ai_agent.py` | Medication reminder worker and optional Gemini assistant |
| `fingerprint_agent.py` | Fingerprint identification and medication-intake workflow |
| `templates/index.html` | Current reference web dashboard |
| `static/` | Static frontend assets |
| `pi_client/` | Raspberry Pi test client, AS608 bridge, and systemd services |
| `..\elderly_healthcare_v3.sql` | Canonical MariaDB/MySQL schema and sample data |
| `API_DOCUMENTATION.md` | Complete frontend API contract |
| `config/` | Safe configuration templates |
| `tests/` | Backend tests |

## Requirements

### Windows Flask server

- Windows with XAMPP installed
- XAMPP Apache is optional; XAMPP MySQL/MariaDB is required
- Python 3.11+ recommended
- A Python virtual environment
- Dependencies listed in `requirements.txt`

### Raspberry Pi

- Raspberry Pi OS with network access to the Windows laptop
- Python 3
- `requests`
- `pyfingerprint` for a real AS608 sensor
- AS608 connected to the Pi serial interface

## 1. Configure XAMPP database

1. Open **XAMPP Control Panel**.
2. Start **MySQL**. Apache is not required for this Flask application.
3. Open phpMyAdmin at `http://127.0.0.1/phpmyadmin`.
4. Import `..\elderly_healthcare_v3.sql` from the workspace parent folder.
5. Confirm that database `elderly_healthcare_v3` exists and contains tables including:
   - `users`
   - `elderly_residents`
   - `medications`
   - `medication_schedules`
   - `medication_schedule_times`
   - `medication_intakes`
   - `notifications`

XAMPP commonly uses:

- Host: `127.0.0.1`
- Port: `3306`
- User: `root`
- Password: blank unless you configured one
- Database: `elderly_healthcare_v3`

Use the actual password configured in your XAMPP installation. Never commit it.

## 2. Configure and run Flask

Create a local `.env` file by copying `.env.example`, or use the more focused template `config/xampp.env.example`. Fill in the database values.

Example local values:

```text
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=elderly_healthcare_v3
FLASK_RUN_HOST=0.0.0.0
FLASK_RUN_PORT=5000
```

From PowerShell, install dependencies and start the server from `SEHCS_WEB` using the project virtual environment:

```powershell
. ..\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If your virtual environment is located elsewhere, activate that environment instead. `pyfingerprint` is not required on the Windows Flask server.

The server should be available at:

- Same Windows machine: `http://127.0.0.1:5000`
- Other devices: `http://<WINDOWS_LAPTOP_IP>:5000`

The app binds to `0.0.0.0` when run directly, allowing the Pi and a React development server on the LAN to reach it.

### Verify Flask

Open these URLs or call them from a browser/API client:

- `http://127.0.0.1:5000/` — reference dashboard
- `http://127.0.0.1:5000/api/residents`
- `http://127.0.0.1:5000/api/medications`
- `http://127.0.0.1:5000/api/notifications`
- `http://127.0.0.1:5000/api/notification-worker/status`

If a database endpoint returns `503`, check that XAMPP MySQL is running and that `DB_PASSWORD` matches the XAMPP account.

## 3. Connect Raspberry Pi to Flask

The Pi communicates with Flask using HTTP JSON. Both devices must be on the same Wi-Fi/Ethernet network, or the Windows laptop must be reachable through a configured hotspot.

### Find the Windows laptop IP

On Windows, find the IPv4 address of the active Wi-Fi/Ethernet adapter. Use that address—not `127.0.0.1`—in the Pi configuration. For example:

```text
Windows laptop: 192.168.1.25
Flask API:      http://192.168.1.25:5000
Pi:             192.168.1.40
```

`127.0.0.1` means “this same device”; on the Pi it would mean the Pi itself, not the Windows laptop.

### Prepare the Pi

On the Pi:

1. Copy `pi_client/` to `/home/pi/SEHCS_WEB/pi_client`.
2. Create a virtual environment.
3. Install `requests`.
4. Install `pyfingerprint` when using the AS608 hardware.
5. Copy and fill in `pi_client/pi.env.example` for the server URL and serial device.

The AS608 device is commonly `/dev/serial0`, `/dev/ttyUSB0`, or `/dev/ttyAMA0`, depending on the wiring and Pi configuration.

### Test the HTTP channel without hardware

From the Pi, send a test resident ID:

```bash
python fingerprint_client.py --server http://<WINDOWS_LAPTOP_IP>:5000 --id 7
```

A successful HTTP request proves the network channel and Flask endpoint are reachable. The backend may still return a workflow failure if resident `7` has no matching schedule near the current time.

### Test the real AS608 bridge

Enroll a resident template:

```bash
python fingerprint_sensor_bridge.py --server http://<WINDOWS_LAPTOP_IP>:5000 --device /dev/serial0 --once --enroll-resident 7
```

Then scan the enrolled finger:

```bash
python fingerprint_sensor_bridge.py --server http://<WINDOWS_LAPTOP_IP>:5000 --device /dev/serial0 --once
```

The bridge sends a recognized sensor position as `fingerprint_id`. For this project’s current test mapping, that number is treated as the resident ID. The Flask fingerprint agent then checks today’s active medication schedules and records a `taken` intake when a schedule is within the configured announcement window.

## 4. Run the Pi bridge at startup

The supplied service file is `pi_client/fingerprint_bridge.service`.

Before installing it, edit these placeholders:

- `<FLASK_SERVER_IP>` → Windows laptop IP
- `/dev/serial0` → actual AS608 serial device
- Python path if your Pi virtual environment is different

Install and enable it on the Pi:

```bash
sudo cp fingerprint_bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fingerprint_bridge.service
sudo systemctl status fingerprint_bridge.service
sudo journalctl -u fingerprint_bridge.service -f
```

The simpler `fingerprint_client.service` is for sending a fixed test resident ID and does not read the AS608 sensor.

## 5. API and frontend integration

The full API contract is in [`API_DOCUMENTATION.md`](API_DOCUMENTATION.md). Important endpoints include:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/residents` | List residents |
| `POST` | `/api/patients` | Create a resident |
| `GET` | `/api/medications` | List medications |
| `POST` | `/api/medications` | Create a medication |
| `PUT/PATCH` | `/api/medications/{id}` | Update a medication |
| `GET` | `/api/notifications` | List notifications |
| `POST` | `/api/notifications` | Create a notification |
| `GET` | `/api/medication-schedules` | List schedules |
| `GET` | `/api/medication-intakes` | List adherence records |
| `POST` | `/api/fingerprint-checkin` | Process a fingerprint check-in |
| `GET` | `/api/notification-worker/status` | Check reminder worker |

A React frontend running on port `3000` or `5173` should use a development proxy or the backend must be configured with CORS. Do not place XAMPP credentials in React environment variables.

## 6. Environment variables

| Variable | Default/use |
| --- | --- |
| `DB_HOST` | XAMPP database host, normally `127.0.0.1` |
| `DB_PORT` | XAMPP database port, normally `3306` |
| `DB_USER` | Usually `root` for local XAMPP |
| `DB_PASSWORD` | XAMPP MySQL password; keep secret |
| `DB_NAME` | `elderly_healthcare_v3` |
| `FLASK_RUN_HOST` | Flask host, use `0.0.0.0` for Pi/LAN access |
| `FLASK_RUN_PORT` / `PORT` | Flask port, normally `5000` |
| `ANNOUNCEMENT_WINDOW_MINUTES` | Fingerprint/reminder matching window, default `10` |
| `MONITOR_INTERVAL_SECONDS` | Background worker interval, default `300` |
| `DISABLE_NOTIFICATION_WORKER` | Set `1` to disable the background worker |
| `GEMINI_API_KEY` | Optional key for the chatbot feature |
| `GEMINI_MODEL` | Optional Gemini model name |

## 7. Troubleshooting

### Flask cannot connect to XAMPP

- Confirm MySQL is green/running in XAMPP.
- Confirm the database name is exactly `elderly_healthcare_v3`.
- Confirm the user and password in `.env`.
- Confirm XAMPP is listening on port `3306`.
- Try `127.0.0.1` instead of `localhost`.

### Pi cannot reach Flask

- Use the Windows laptop’s LAN IPv4 address, not `127.0.0.1`.
- Confirm Flask is running with host `0.0.0.0`.
- Allow Python/port `5000` through Windows Firewall on a trusted private network.
- Confirm both devices are on the same network.
- From the Pi, check the Flask URL in a browser or with `curl`.

### AS608 is not detected

- Check the ribbon/serial wiring and power supply.
- Check the device path with `ls -l /dev/serial0 /dev/ttyUSB* /dev/ttyAMA*`.
- Confirm `pyfingerprint` is installed in the same virtual environment used by the service.
- Stop other services that may already be using the serial port.
- Review logs with `journalctl -u fingerprint_bridge.service -f`.

### Fingerprint is recognized but intake is not recorded

- Confirm the resident exists in `elderly_residents`.
- Confirm the resident has an active schedule for today.
- Confirm a schedule time is within `ANNOUNCEMENT_WINDOW_MINUTES`.
- Review `/api/medication-intakes` and Flask logs.

## Security notes

- Never commit `.env` or database passwords.
- The current API has no authentication or authorization layer; use it only on a trusted development network until authentication is added.
- Restrict Windows Firewall port `5000` to the trusted LAN where possible.
- Protect or remove `/api/_debug/routes` before production deployment.
- Fingerprint templates are sensitive biometric data; secure the database and restrict enrollment access.
