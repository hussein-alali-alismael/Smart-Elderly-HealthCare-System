Pi client for sending fingerprint payloads to the Flask server

Place the `fingerprint_client.py` script on the Raspberry Pi under `/home/pi/SEHCS_WEB/pi_client`.

Install runtime requirements (on the Pi):

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
python3 -m venv ~/Desktop/SEHCS
source ~/Desktop/SEHCS/bin/activate
pip install requests
```

To test sending a fake resident id (7) to your Flask server on the laptop:

```bash
python fingerprint_client.py --server http://127.0.0.1:5000 --id 7
```

To run automatically at boot copy `fingerprint_client.service` to `/etc/systemd/system/` and enable it:

```bash
sudo cp fingerprint_client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fingerprint_client.service
```

Edit the `ExecStart` in the service file to point to your Flask server IP and the correct python path if needed.

AS608 sensor bridge
-------------------

If you have an AS608 fingerprint reader attached to the Pi, use `fingerprint_sensor_bridge.py` to read templates and forward them to the Flask server. Example:

```bash
python fingerprint_sensor_bridge.py --server http://<FLASK_SERVER_IP>:5000 --device /dev/ttyUSB0
```

Install the optional dependency for the sensor:

```bash
pip install pyfingerprint
```

Voice prompts and results are enabled by default on the Pi. Install a speech
engine and speaker support:

```bash
sudo apt install -y espeak-ng alsa-utils
```

Run with voice:

```bash
python fingerprint_sensor_bridge.py --server http://<FLASK_SERVER_IP>:5000 --device /dev/serial0
```

Disable speech when needed with `--no-voice`. The bridge speaks short messages
only; the complete server response is still displayed and saved in the JSON
history file. The Pi is the recommended voice device, so Flask server speech is
disabled by default to prevent duplicate announcements.

To enable schedule-reminder speech on the computer running Flask, set
`SEHCS_SERVER_VOICE_ENABLED=true` in its environment. On Windows, speech uses
PowerShell's built-in speech engine; on Linux it uses `espeak-ng` or `espeak`.
Fingerprint check-in messages remain spoken by the Pi, avoiding duplicate audio.

Set `SEHCS_TTS_VOICE=ar` for Arabic on a Pi if the Arabic voice is installed;
use `en` for English. Available voices depend on the operating system and
installed speech packages.

The bridge uses the AS608's internal fingerprint search for normal check-in. The sensor position is sent to Flask as `fingerprint_id`; Flask treats that position as the resident id for this test setup. Raw templates are sent only during enrollment.

Enroll one fingerprint for resident 7:

```bash
python fingerprint_sensor_bridge.py --server http://<FLASK_SERVER_IP>:5000 --device /dev/serial0 --once --enroll-resident 7
```

Then scan the same finger normally:

```bash
python fingerprint_sensor_bridge.py --server http://<FLASK_SERVER_IP>:5000 --device /dev/serial0 --once
```

For continuous scanning, omit `--once`. The program keeps running, displays a
readable result after every scan, and saves the complete responses to
`fingerprint_results.json`. Type `q` and press Enter to stop, or press
`Ctrl+C`:

```bash
python fingerprint_sensor_bridge.py --server http://<FLASK_SERVER_IP>:5000 --device /dev/serial0 --json-file fingerprint_results.json
```

Use `--test-resident 7` only when the AS608 slot is also position 7. A
recognized fingerprint in another sensor position is rejected rather than
being incorrectly assigned to resident 7.

The Flask agent will identify resident 7, load today's medication schedule, select the nearest scheduled time, and record the intake when it is within the configured time window.

Run bridge as a systemd service
------------------------------

To run the AS608 bridge automatically at boot, copy the provided `fingerprint_bridge.service` to `/etc/systemd/system/`, update the `ExecStart` placeholders (`<FLASK_SERVER_IP>` and device path) to match your setup, then enable the service:

```bash
sudo cp fingerprint_bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fingerprint_bridge.service

# Check status and logs
sudo systemctl status fingerprint_bridge.service
sudo journalctl -u fingerprint_bridge.service -f
```

If you prefer to run the sensor bridge in simulate mode on boot (useful for testing without hardware), change the `ExecStart` to include `--simulate` and remove the `--device` flag.
