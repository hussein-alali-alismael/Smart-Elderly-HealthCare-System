---
noteId: "9fb49d00a3b811f19947b7c0e2bbb36a"
tags: []

---

# SEHCS Web Application - Issue Fixes Summary

## ✅ Issue 1: Frontend Page Routing (FIXED)
**Problem:** After login, switching between pages (medications, notifications, etc.) stayed on the main dashboard page.

**Root Cause:** The route handler `/<page>.html` was returning `index.html` for all requests instead of the corresponding template.

**Solution Applied:**
- Updated `app.py` line 283-289 to return the correct template file:
  ```python
  @app.route("/<page>.html")
  def frontend_page(page):
      """Serve individual dashboard pages with authentication."""
      if "user_id" not in session:
          return redirect("/login")
      allowed_pages = {"index", "live", "medications", "notifications", "patient_details"}
      if page not in allowed_pages:
          return jsonify({"error": "Page not found."}), 404
      return render_template(f"{page}.html", csrf_token=generate_csrf())
  ```

**Testing:** ✅ All pages now load correctly:
- `http://127.0.0.1:5000/medications.html` → Shows medications page
- `http://127.0.0.1:5000/notifications.html` → Shows notifications page
- `http://127.0.0.1:5000/live.html` → Shows live monitoring page
- `http://127.0.0.1:5000/patient_details.html` → Shows patient details page

---

## ✅ Issue 2: Raspberry Pi CSRF Token Problem (FIXED)
**Problem:** Raspberry Pi fingerprint check-in returns: `"status": 401, "text": "Fingerprint device authentication required."`

**Root Cause:** 
1. The `/api/fingerprint-checkin` endpoint lacked `@csrf.exempt` decorator (blocking CSRF errors)
2. The Raspberry Pi script wasn't sending the `FINGERPRINT_DEVICE_TOKEN` in the request headers

**Solution Applied:**
1. Added `@csrf.exempt` decorator to fingerprint endpoint:
   ```python
   @app.route("/api/fingerprint-checkin", methods=["POST"])
   @csrf.exempt
   def fingerprint_checkin():
   ```

2. Added `@csrf.exempt` to fall-alerts endpoint:
   ```python
   @app.route("/api/fall-alerts", methods=["POST"])
   @csrf.exempt
   def fall_alert():
   ```

3. Configured device tokens in Flask `.env`:
   ```
   FINGERPRINT_DEVICE_TOKEN=d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b
   FALL_ALERT_DEVICE_TOKEN=c4a9e1f3b8d6c2e5a7f9d1b3e6c8a2f4d7b9e1c3f5a7d9b2e4c6f8a1d3e5g7
   ```

4. **Raspberry Pi Setup:** Configure `.env` on Raspberry Pi to send the device token:
   ```bash
   # On Raspberry Pi: pi_client/.env
   source .env
   python fingerprint_sensor_bridge.py --server $FLASK_SERVER_URL --device $FINGERPRINT_DEVICE --once
   ```

**Testing:** ✅ Fingerprint endpoint now accepts device requests with proper authentication:
```bash
curl -X POST "http://127.0.0.1:5000/api/fingerprint-checkin" \
  -H "Content-Type: application/json" \
  -H "X-Fingerprint-Token: d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b" \
  -d '{"fingerprint_id":7}'
```

**For Raspberry Pi Integration:**
- The `fingerprint_sensor_bridge.py` script automatically reads `FINGERPRINT_DEVICE_TOKEN` from environment variables
- Use device token: `d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b`
- Token is sent with header: `X-Fingerprint-Token: <device_token>`
- Payload: `{"fingerprint_id": <resident_id>}` or `{"fingerprintTemplate": "<base64_data>"}`

**📖 Setup Guide:** See [pi_client/RASPBERRY_PI_SETUP.md](pi_client/RASPBERRY_PI_SETUP.md) for complete Raspberry Pi configuration instructions.

---

## ⚠️ Issue 3: IP 10.16.161.225 Returns 500 Privoxy Error
**Status:** Network Infrastructure Issue (outside Flask scope)

**Observations:**
- Flask is running on `0.0.0.0:5000` (all interfaces)
- Both `127.0.0.1:5000` and `10.16.161.225:5000` are accessible
- Error mentions "Privoxy" - a filtering proxy server
- This indicates network/firewall/proxy configuration issue

**Possible Causes:**
1. **Proxy Filtering:** Privoxy proxy is intercepting/filtering requests from that IP
2. **Firewall Rules:** Network firewall blocking or routing traffic from 10.16.161.225
3. **Network Configuration:** Gateway or router issue with that IP range
4. **Reverse Proxy:** An intermediate reverse proxy returning the error

**Troubleshooting Steps:**
1. Check if 10.16.161.225 can reach 127.0.0.1:5000:
   ```bash
   curl http://127.0.0.1:5000/health
   ```

2. Check network connectivity from the device on 10.16.161.225:
   ```bash
   ping 10.16.161.225
   curl http://10.16.161.225:5000/health
   ```

3. Check if a proxy is configured:
   - Disable any VPN/proxy software
   - Check environment variables: `echo %HTTP_PROXY%`, `echo %HTTPS_PROXY%`
   - Check firewall settings for Privoxy or other proxies

4. Try direct curl from another machine on the network:
   ```bash
   curl http://10.16.161.225:5000/login
   ```

**Recommendation:** This is likely a network/infrastructure issue. Contact your network administrator to check for proxy/firewall rules blocking that IP address.

---

## Summary of Changes to Flask Application

### Files Modified:
1. **app.py**
   - Line 283: Added authentication check to dashboard page routes
   - Line 290: Changed `render_template("index.html")` → `render_template(f"{page}.html", csrf_token=generate_csrf())`
   - Line 602: Added `@csrf.exempt` decorator to `/api/fingerprint-checkin`
   - Line 630: Added `@csrf.exempt` decorator to `/api/fall-alerts`

2. **.env**
   - Added `FINGERPRINT_DEVICE_TOKEN=d7f9e2c1a8b3f5e4d6c2a9b1e7f3d5c8a2b4e6f8d1c3e5a7b9f2d4c6e8a0b`
   - Added `FALL_ALERT_DEVICE_TOKEN=c4a9e1f3b8d6c2e5a7f9d1b3e6c8a2f4d7b9e1c3f5a7d9b2e4c6f8a1d3e5g7`

### No Breaking Changes:
- All existing API endpoints continue to work
- Authentication flow unchanged
- Dashboard functionality preserved
- User data isolation maintained

---

## Testing Checklist

- [x] Login with `test-user-001` works
- [x] Dashboard loads with patient data
- [x] Navigation to medications page works
- [x] Navigation to notifications page works
- [x] Navigation to live monitoring page works
- [x] CSRF token injected in meta tags on all pages
- [x] Fingerprint endpoint accepts device token
- [x] Fall alerts endpoint accepts device token
- [x] User data isolation working (user only sees their own residents/medications)

---

## Deployment Notes

1. **Update Device Tokens:** Replace the sample tokens with your own secure tokens in production
2. **Configure FLASK_RUN_HOST:** Ensure Flask is accessible on your network (currently `0.0.0.0`)
3. **Use WSGI Server:** For production, use Gunicorn or uWSGI instead of Flask development server
4. **Enable HTTPS:** Set `SESSION_COOKIE_SECURE=1` when using HTTPS
5. **Network Access:** Ensure firewall/proxy rules allow access to port 5000

---

## Quick Reference - API Endpoints

### Authentication
- `POST /api/auth/login` - Login with openId
- `POST /api/auth/signup` - Create new user account
- `POST /api/auth/logout` - Logout and clear session
- `GET /api/csrf-token` - Get CSRF token (if not in meta tag)

### Resident Management (Auth Required)
- `GET /api/residents` - List all residents for user
- `POST /api/residents` - Create new resident
- `GET /api/residents/{id}` - Get resident details
- `POST /api/residents/{id}` - Update resident

### Medications (Auth Required)
- `GET /api/medications` - List all medications for user
- `POST /api/medications` - Create new medication
- `GET /api/medications/{id}` - Get medication details

### Device Endpoints (Device Token Required)
- `POST /api/fingerprint-checkin` - Fingerprint check-in (X-Fingerprint-Token header)
- `POST /api/fall-alerts` - Fall alert report (X-Fall-Alert-Token header)

---

Last Updated: 2026-08-29
