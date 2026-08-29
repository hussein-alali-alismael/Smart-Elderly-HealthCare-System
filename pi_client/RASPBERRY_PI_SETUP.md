---
noteId: "05f92f90a3b911f19947b7c0e2bbb36a"
tags: []

---

# Raspberry Pi Fingerprint Sensor Bridge - Setup Guide

## 🔑 Issue: Fingerprint Check-in Returns 401 "Authentication Required"

The Raspberry Pi script is correctly built and sending requests, but the Flask server doesn't recognize the device without the authentication token.

## ✅ Solution: Configure Device Token

### Step 1: Copy the Configuration File

On your Raspberry Pi, navigate to the SEHCS project directory and create the `.env` file:

```bash
cd ~/Desktop/SEHCS/
cp pi_client/pi.env.example .env
```

### Step 2: Edit the .env File

```bash
nano .env
```

Update with these values:

```env
# Raspberry Pi -> Flask connection settings
FLASK_SERVER_URL=http://10.16.161.225:5000
FINGERPRINT_DEVICE_TOKEN=d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b

# AS608 Configuration
FINGERPRINT_DEVICE=/dev/serial0
FINGERPRINT_BAUDRATE=57600
FINGERPRINT_POLL_SECONDS=2
FINGERPRINT_RETRIES=5
```

**Key Points:**
- `FLASK_SERVER_URL`: Must match your Flask server's actual IP and port
- `FINGERPRINT_DEVICE_TOKEN`: **Must be exactly this value** - it matches the token in the Flask server's `.env` file
- `FINGERPRINT_DEVICE`: The serial port where your AS608 fingerprint reader is connected

### Step 3: Load Environment Variables Before Running

**Option A: Source the .env file (recommended)**

```bash
# From the project root directory
source .env
python pi_client/fingerprint_sensor_bridge.py --server $FLASK_SERVER_URL --device $FINGERPRINT_DEVICE --once
```

**Option B: Set environment variables manually**

```bash
export FINGERPRINT_DEVICE_TOKEN="d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b"
python fingerprint_sensor_bridge.py --server http://10.16.161.225:5000 --device /dev/serial0 --once
```

**Option C: Create a startup script**

Create `run_fingerprint.sh`:

```bash
#!/bin/bash
cd ~/Desktop/SEHCS/
source .env
python pi_client/fingerprint_sensor_bridge.py --server "$FLASK_SERVER_URL" --device "$FINGERPRINT_DEVICE" --once
```

Then run it:
```bash
chmod +x run_fingerprint.sh
./run_fingerprint.sh
```

### Step 4: Verify Token is Being Sent

Run with the environment variable set and you should see:

```
Waiting for finger...
AS608 search result: position=2, accuracy=109
Captured fingerprint.
Sending payload to fingerprint check-in endpoint...

==========================================================
Fingerprint check-in result
----------------------------------------------------------
Network: SUCCESS
Resident: John Doe (ID 2)
Status:   Fingerprint matched resident
Step:     check_in_success
...
```

## 🔍 Troubleshooting

### Error: "Fingerprint device authentication required"
- The `FINGERPRINT_DEVICE_TOKEN` environment variable is not set or is empty
- Solution: Make sure you've run `source .env` before executing the script

### Error: "401 Unauthorized"
- The token value is incorrect or doesn't match the Flask server
- Solution: Double-check that the token matches exactly: `d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b`

### Error: "Cannot connect to http://10.16.161.225:5000"
- Network connectivity issue
- Solution: Test with `curl http://10.16.161.225:5000/login`

### Error: "AS608 not found on /dev/serial0"
- The fingerprint sensor is not connected or at wrong device path
- Solution: Run `ls /dev/tty*` to find the correct serial port

## 📝 Setup for Systemd Service (Optional)

To run the script as a system service:

1. Create service file `/etc/systemd/system/fingerprint-bridge.service`:

```ini
[Unit]
Description=SEHCS Fingerprint Sensor Bridge
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Desktop/SEHCS
EnvironmentFile=/home/pi/Desktop/SEHCS/.env
ExecStart=/usr/bin/python3 pi_client/fingerprint_sensor_bridge.py --server ${FLASK_SERVER_URL} --device ${FINGERPRINT_DEVICE}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

2. Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable fingerprint-bridge
sudo systemctl start fingerprint-bridge
```

3. Check status:
```bash
sudo systemctl status fingerprint-bridge
```

## 🧪 Quick Test

To verify the connection without a real fingerprint sensor:

```bash
# Test with simulation
cd ~/Desktop/SEHCS/
source .env
python pi_client/fingerprint_sensor_bridge.py --server $FLASK_SERVER_URL --simulate --once
```

This creates a fake fingerprint and tests the entire endpoint without needing the sensor.

---

**Key Token:** `d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b`

**Server URL:** `http://10.16.161.225:5000`

Once you've set up the .env file with these values and sourced it, the script will send the device token with every request and fingerprints will check in successfully! 🎯
