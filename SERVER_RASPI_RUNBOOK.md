# SEHCS Server + Raspberry Pi Runbook

This document explains the complete daily startup and one-time setup for the SEHCS Flask server, Raspberry Pi fingerprint bridge, Bluetooth speaker, Piper voice, and medication reminder worker.

## System layout

- **Windows laptop:** Flask server, MariaDB/XAMPP, scheduler, and dashboard.
- **Raspberry Pi:** AS608 fingerprint reader, Bluetooth speaker, Piper voice service.
- **Network:** Both devices must be on the same LAN or hotspot.
- **Flask API:** laptop port `5000`.
- **Pi voice API:** Raspberry Pi port `5051`.

The laptop does not speak when `SEHCS_VOICE_DEVICE_URL` is configured. It sends text to the Pi, and the Pi speaks through the Bluetooth speaker.

## One-time Windows setup

Open PowerShell in `D:\flask\SEHCS_WEB` and activate the project environment:

```powershell
D:\flask\Scripts\Activate.ps1
```

Confirm `.env` contains these values. Do not commit or share this file:

```env
FLASK_RUN_HOST=10.16.161.225
FLASK_RUN_PORT=5000
SEHCS_SERVER_VOICE_ENABLED=true
SEHCS_VOICE_DEVICE_URL=http://<PI_IP_ADDRESS>:5051
SEHCS_DEVICE_TOKEN=<one-shared-token-used-by-the-Pi>
ANNOUNCEMENT_WINDOW_MINUTES=10
MONITOR_INTERVAL_SECONDS=300
```

Replace `<PI_IP_ADDRESS>` with the Pi address shown by `hostname -I`.

The laptop firewall must allow inbound TCP port `5000` on the trusted private network.
The `.flaskenv` file binds Flask to the Wi-Fi address `10.16.161.225` used by
the Raspberry Pi. If Windows receives a new Wi-Fi address, update `.flaskenv`
and the Pi's `FLASK_SERVER_URL` together.

## If the laptop IP changes

The Flask terminal shows the laptop's current LAN address after `Running on`.
In this example the current address is `10.0.0.2`. Update the Pi environment:

```bash
cd ~/Desktop/SEHCS
dos2unix .env
sed -i 's#^FLASK_SERVER_URL=.*#FLASK_SERVER_URL=http://10.0.0.2:5000#' .env
source .env
```

Confirm the value:

```bash
echo "$FLASK_SERVER_URL"
```

Then restart only the fingerprint bridge. The Pi voice service does not need a
restart for a laptop-IP change:

```bash
python fingerprint_sensor_bridge.py --server "$FLASK_SERVER_URL" --device "$FINGERPRINT_DEVICE"
```

For a permanent solution, create a DHCP reservation in the router or hotspot
for the Windows laptop, or configure a fixed private IPv4 address. Ideally
reserve both devices so their addresses do not change. Do not use `127.0.0.1`
in the Pi `.env`; on the Pi that means the Pi itself, not Windows.

## One-time Raspberry Pi setup

From the Pi:

```bash
cd ~/Desktop/SEHCS
python3 -m venv bin
source bin/activate
pip install requests piper-tts
sudo apt update
sudo apt install -y dos2unix alsa-utils
```

If the project was copied from Windows, convert the environment file once:

```bash
dos2unix ~/Desktop/SEHCS/.env
```

Create or edit the Pi environment:

```bash
nano ~/Desktop/SEHCS/.env
```

Use these settings:

```env
SEHCS_DEVICE_TOKEN=<same-token-as-Windows>
SEHCS_VOICE_BIND_HOST=0.0.0.0
SEHCS_VOICE_PORT=5051
SEHCS_VOICE_ENABLED=true
SEHCS_TTS_ENGINE=piper
SEHCS_PIPER_MODEL=/home/raspi/models/en_US-lessac-medium.onnx
SEHCS_AUDIO_PLAYER=pw-play
SEHCS_AUDIO_DEVICE=
```

## Piper model setup

Create the model directory and download both required files:

```bash
mkdir -p /home/raspi/models
wget -O /home/raspi/models/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget -O /home/raspi/models/en_US-lessac-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

Verify the model path:

```bash
ls -lh /home/raspi/models/en_US-lessac-medium.onnx*
echo "$SEHCS_PIPER_MODEL"
```

Both `.onnx` and `.onnx.json` files are required. An error mentioning `..json` usually means `SEHCS_PIPER_MODEL` is empty or incorrectly set.

## Bluetooth speaker setup

Put the speaker in pairing mode:

```bash
bluetoothctl
```

Inside `bluetoothctl`:

```text
power on
agent on
default-agent
scan on
```

When the speaker appears, use its MAC address:

```text
pair XX:XX:XX:XX:XX:XX
trust XX:XX:XX:XX:XX:XX
connect XX:XX:XX:XX:XX:XX
scan off
quit
```

Confirm the Bluetooth sink is present and selected:

```bash
wpctl status
```

The connected speaker should appear under `Sinks` with a `*`, for example `BT SPEAKER`. Set it as default if necessary:

```bash
wpctl set-default <SINK_ID>
```

Test Piper and Bluetooth playback:

```bash
echo "This is a medication reminder" | piper --model "$SEHCS_PIPER_MODEL" --output_file /tmp/test.wav
pw-play /tmp/test.wav
```

If `pw-play` is unavailable:

```bash
sudo apt install -y pipewire pipewire-pulse wireplumber
```

Do not use `plughw:Headphones,0` for Bluetooth. That is the wired headphone output.

## Install the automatic Pi voice service

The user’s current Pi layout has `voice_server.py` in the project root:

```text
/home/raspi/Desktop/SEHCS/voice_server.py
```

Install the service file from the project root:

```bash
sudo cp ~/Desktop/SEHCS/sehcs-voice.service /etc/systemd/system/
```

The service must contain this `ExecStart` line:

```ini
ExecStart=/home/raspi/Desktop/SEHCS/bin/python /home/raspi/Desktop/SEHCS/voice_server.py
```

Enable it permanently:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sehcs-voice.service
sudo systemctl status sehcs-voice.service
```

The service loads `/home/raspi/Desktop/SEHCS/.env` automatically. You do not need to run `source .env` each time.

Check logs:

```bash
journalctl -u sehcs-voice.service -f
```

## Daily startup

### Raspberry Pi

Normally nothing is required after boot because systemd starts the voice service. Confirm the speaker is connected:

```bash
wpctl status
sudo systemctl status sehcs-voice.service
```

If the Bluetooth speaker was turned off, reconnect it:

```bash
bluetoothctl connect XX:XX:XX:XX:XX:XX
```

### Windows laptop

Start XAMPP/MariaDB first, then open PowerShell:

```powershell
Set-Location D:\flask\SEHCS_WEB
D:\flask\Scripts\Activate.ps1
python app.py
```

Leave this terminal running. Flask starts the medication reminder worker automatically unless `DISABLE_NOTIFICATION_WORKER=1` is set.

The worker checks every `MONITOR_INTERVAL_SECONDS` seconds. A reminder is announced when it is within `ANNOUNCEMENT_WINDOW_MINUTES` of the scheduled time.

## Test the complete voice path

From the Windows laptop, replace the token with the value in both `.env` files:

```powershell
curl.exe -X POST http://<PI_IP_ADDRESS>:5051/speak -H "X-Voice-Token: <VOICE_TOKEN>" -H "Content-Type: application/json" -d '{"message":"Medication reminder test"}'
```

Expected response:

```json
{"ok": true}
```

Check the Pi service:

```bash
sudo systemctl status sehcs-voice.service
journalctl -u sehcs-voice.service -n 40 --no-pager
```

Check the Flask reminder worker using the authenticated dashboard session or a local log. The Flask log should show `Notification worker started` and, when due, `Notification worker stored ... reminder(s)`.

## Fingerprint operation

Start the fingerprint bridge manually when testing hardware:

```bash
cd ~/Desktop/SEHCS
source bin/activate
python pi_client/fingerprint_sensor_bridge.py --server http://<LAPTOP_IP_ADDRESS>:5000 --device /dev/serial0
```

The bridge speaks server success and error messages locally on the Pi. It no longer speaks the initial `Please place your finger on the sensor` prompt.

The Flask server requires the fingerprint token header. The bridge reads
`SEHCS_DEVICE_TOKEN` from the Pi `.env`.

## Troubleshooting

### `.env: command not found` or `$'\\r'`

The file has Windows CRLF line endings:

```bash
dos2unix ~/Desktop/SEHCS/.env
```

### Service looks for `pi_client/voice_server.py`

The installed service file is old. Replace it and reload systemd:

```bash
sudo cp ~/Desktop/SEHCS/sehcs-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart sehcs-voice.service
systemctl cat sehcs-voice.service
```

Confirm it points to `/home/raspi/Desktop/SEHCS/voice_server.py`.

### Piper says it cannot open `..json`

Check these values:

```bash
source ~/Desktop/SEHCS/.env
echo "$SEHCS_PIPER_MODEL"
ls -lh "$SEHCS_PIPER_MODEL" "$SEHCS_PIPER_MODEL.json"
```

The model and matching JSON file must both exist.

### `aplay` reports audio error 524

Use PipeWire for Bluetooth:

```bash
wpctl status
pw-play /tmp/test.wav
```

Set:

```env
SEHCS_AUDIO_PLAYER=pw-play
SEHCS_AUDIO_DEVICE=
```

### Bluetooth speaker is connected but silent

Confirm it appears under `Sinks` with `*` in `wpctl status`. Then test:

```bash
pw-play /tmp/test.wav
```

If the speaker is not the default:

```bash
wpctl set-default <SINK_ID>
```

### Reminder does not speak

1. Confirm the Pi service is active.
2. Confirm `SEHCS_VOICE_DEVICE_URL` and `SEHCS_DEVICE_TOKEN` are correct on Windows.
3. Restart Flask after changing `.env`.
4. Confirm the reminder is within the 10-minute window.
5. Confirm the medication notification is not already spoken in the current Flask process.
6. Check Flask logs for a connection or HTTP error.

### Pi voice service returns HTTP 401

The laptop is reaching the Pi, but the `SEHCS_DEVICE_TOKEN` values do
not match, or systemd is still using the old value. On the Pi, edit the
environment file and set the token to exactly the same value as the laptop:

```bash
nano ~/Desktop/SEHCS/.env
```

The line must be:

```env
SEHCS_DEVICE_TOKEN=<exact-value-from-the-Windows-.env>
```

Then run:

```bash
dos2unix ~/Desktop/SEHCS/.env
sudo systemctl daemon-reload
sudo systemctl restart sehcs-voice.service
sudo systemctl status sehcs-voice.service
```

Do not run only `source .env`; the systemd service has its own environment and
must be restarted after `.env` changes. To confirm the service loaded a token
without displaying it:

```bash
sudo systemctl show sehcs-voice.service -p Environment | sed 's/SEHCS_DEVICE_TOKEN=[^ ]*/SEHCS_DEVICE_TOKEN=*** /'
```

From Windows, test the same token against the Pi:

```powershell
curl.exe -X POST http://<PI_IP_ADDRESS>:5051/speak -H "X-Voice-Token: <exact-token>" -H "Content-Type: application/json" -d '{"message":"Voice authentication test"}'
```

Expected response is HTTP `202` with `{"ok": true}`. Restart Flask after any
Windows `.env` change as well.

## Security

Use one long random `SEHCS_DEVICE_TOKEN` for the Pi device flows, plus a
separate `FLASK_SECRET_KEY`. Rotate any token that has been pasted into chat,
terminal screenshots, or public files. Never commit `.env` or biometric data.
