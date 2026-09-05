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

Voice prompts and results are enabled by default on the Pi. The Pi is the
recommended single sound source for schedule, fingerprint, and fall messages.
Install a speech engine and speaker support:

```bash
sudo apt install -y espeak-ng alsa-utils
```

Test the speaker before starting the service:

```bash
espeak-ng "SEHCS voice test"
```

If `aplay` reports `audio open error: Unknown error 524`, the default ALSA
device is unavailable. List the actual devices:

```bash
aplay -l
aplay -L
```

Then test a listed device, for example:

```bash
aplay -D plughw:0,0 /tmp/test.wav
```

If that works, add this to `~/Desktop/SEHCS/.env` and restart the service:

```env
SEHCS_AUDIO_DEVICE=plughw:0,0
```

Use the device name shown by your own `aplay -l`; `0,0` is only an example.
For a USB speaker it may be `plughw:1,0`.

For a Bluetooth speaker, connect it and check the PipeWire audio sinks:

```bash
bluetoothctl
power on
connect XX:XX:XX:XX:XX:XX
quit
wpctl status
```

Test the connected speaker with:

```bash
pw-play /tmp/test.wav
```

If that works, use these settings in `.env`:

```env
SEHCS_AUDIO_PLAYER=pw-play
SEHCS_AUDIO_DEVICE=
```

Restart `sehcs-voice.service` after changing `.env`. Do not set
`SEHCS_AUDIO_DEVICE=plughw:Headphones,0` for Bluetooth; that is the wired
headphone output.

Run with voice:

```bash
python fingerprint_sensor_bridge.py --server http://<FLASK_SERVER_IP>:5000 --device /dev/serial0
```

Disable speech when needed with `--no-voice`. The bridge speaks short messages
only; the complete server response is still displayed and saved in the JSON
history file.

To route schedule and fall announcements from Flask to the same Pi speaker,
start the voice service in another terminal:

```bash
export SEHCS_VOICE_DEVICE_TOKEN="replace-with-the-same-voice-token"
python pi_client/voice_server.py
```

To start it automatically at every boot and load `.env` automatically, install
the included systemd service. First convert a `.env` copied from Windows to
Linux line endings:

```bash
sudo apt install -y dos2unix
dos2unix ~/Desktop/SEHCS/.env
sudo cp ~/Desktop/SEHCS/pi_client/sehcs-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sehcs-voice.service
sudo systemctl status sehcs-voice.service
```

View service errors with:

```bash
journalctl -u sehcs-voice.service -f
```

The service reads `/home/raspi/Desktop/SEHCS/.env` itself, so you no longer
need to run `source .env` manually.

On the Flask computer, configure:

```env
SEHCS_SERVER_VOICE_ENABLED=true
SEHCS_VOICE_DEVICE_URL=http://<RASPBERRY_PI_IP>:5051
SEHCS_VOICE_DEVICE_TOKEN=replace-with-the-same-voice-token
```

When `SEHCS_VOICE_DEVICE_URL` is set, Flask sends speech to the Pi and does
not use the laptop speaker. Fingerprint messages continue to be spoken locally
by the Pi bridge.

### Important root-level Pi layout

If your Pi runs the scripts from `~/Desktop/SEHCS` instead of
`~/Desktop/SEHCS/pi_client`, copy the Pi voice helper to the project root:

```bash
cp ~/Desktop/SEHCS/pi_client/voice.py ~/Desktop/SEHCS/voice.py
```

The root `voice.py` must be the Pi helper, not the Flask computer's
`voice.py`. The root `voice_server.py`, fingerprint bridge, and systemd service
all import this root helper. Confirm Piper is selected:

```bash
grep -E '^SEHCS_TTS_ENGINE=|^SEHCS_PIPER_MODEL=|^SEHCS_AUDIO_PLAYER=' ~/Desktop/SEHCS/.env
```

Before running the fingerprint bridge manually, load `.env` in that shell:

```bash
cd ~/Desktop/SEHCS
source .env
python fingerprint_sensor_bridge.py --server "$FLASK_SERVER_URL" --device "$FINGERPRINT_DEVICE"
```

Confirm the root helper is the Piper-capable Pi version:

```bash
grep -n 'SEHCS_TTS_ENGINE\|_speak_with_piper\|Path(sys.executable)' ~/Desktop/SEHCS/voice.py
```

If those lines are missing, replace the root helper:

```bash
cp ~/Desktop/SEHCS/pi_client/voice.py ~/Desktop/SEHCS/voice.py
```

If your Pi has no `pi_client` directory, copy `pi_client/voice.py` from the
Windows project to `/home/raspi/Desktop/SEHCS/voice.py` with `scp`, then run
the `grep` check again. The bridge must be started from a shell where
`SEHCS_TTS_ENGINE=piper` and `SEHCS_PIPER_MODEL` are loaded.

Set `SEHCS_TTS_VOICE=ar` for Arabic on a Pi if the Arabic voice is installed;
use `en` for English. Available voices depend on the operating system and
installed speech packages.

For a more natural accent than eSpeak, Piper can be used locally on the Pi.
Install Piper and download a compatible voice model, then configure:

```env
SEHCS_TTS_ENGINE=piper
SEHCS_PIPER_MODEL=/home/raspi/models/en_US-lessac-medium.onnx
SEHCS_AUDIO_PLAYER=aplay
```

Piper is the default engine for the Pi bridge. If you deliberately choose
`SEHCS_TTS_ENGINE=espeak`, the fallback voice is the female `en+f3` voice.

The bridge uses the AS608's internal fingerprint search for normal check-in and sends the captured `fingerprintTemplate` to Flask. Configure the same `FINGERPRINT_DEVICE_TOKEN` on the Pi and Flask server. Flask performs the resident match from the captured template; a sensor position or resident id alone is not accepted.

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
