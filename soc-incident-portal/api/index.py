"""
SOC Incident Reporting & Alerting Portal
Backend API - Flask application served as a Vercel Python serverless function.

Endpoints:
    GET    /api/incidents            -> list all incidents (supports ?severity=&status=&search=)
    POST   /api/incidents            -> create a new incident (sends email alert)
    GET    /api/incidents/<id>       -> fetch a single incident
    PUT    /api/incidents/<id>       -> update an incident (e.g. status change)
    DELETE /api/incidents/<id>       -> delete an incident
    POST   /api/incidents/<id>/alert -> re-send the email alert for an incident
    GET    /api/health               -> health check / env diagnostics
"""

import json
import os
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
# Vercel serverless functions have a writable /tmp directory that persists
# only for the lifetime of a warm container instance. This is sufficient for
# a demo / low-volume deployment. For real production use, swap this module
# out for a managed database (Vercel Postgres, Supabase, PlanetScale, etc.)
# by replacing the four functions below (_load, _save, _next_id is not
# needed since we use uuid4).

DATA_FILE = "/tmp/soc_incidents.json"

VALID_SEVERITIES = {"Low", "Medium", "High", "Critical"}
VALID_STATUSES = {"Open", "Investigating", "Contained", "Resolved"}


def _seed_data():
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": str(uuid.uuid4()),
            "title": "Suspicious login from unrecognized geolocation",
            "description": "Multiple failed login attempts followed by a successful "
            "authentication from an IP address geolocated outside of approved "
            "regions. Possible credential compromise.",
            "severity": "High",
            "status": "Investigating",
            "reporter": "soc-analyst-01",
            "asset": "auth-gateway-prod",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Outbound traffic spike to known malicious C2 domain",
            "description": "IDS flagged repeated DNS queries to a domain listed on "
            "current threat intelligence feeds as an active command-and-control "
            "endpoint.",
            "severity": "Critical",
            "status": "Open",
            "reporter": "siem-auto-detect",
            "asset": "workstation-fin-014",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Expired TLS certificate on internal API gateway",
            "description": "Certificate monitoring detected an expired TLS "
            "certificate causing intermittent handshake failures.",
            "severity": "Low",
            "status": "Resolved",
            "reporter": "infra-monitoring",
            "asset": "internal-api-gw",
            "created_at": now,
            "updated_at": now,
        },
    ]


def _load():
    if not os.path.exists(DATA_FILE):
        data = _seed_data()
        _save(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        data = _seed_data()
        _save(data)
        return data


def _save(incidents):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(incidents, f, indent=2)


# ---------------------------------------------------------------------------
# Email alert dispatch
# ---------------------------------------------------------------------------

def _build_alert_html(incident):
    severity_colors = {
        "Low": "#38bdf8",
        "Medium": "#fbbf24",
        "High": "#fb923c",
        "Critical": "#f87171",
    }
    color = severity_colors.get(incident["severity"], "#94a3b8")

    return f"""
    <div style="background-color:#0f172a;padding:32px;font-family:'Segoe UI',Arial,sans-serif;">
      <div style="max-width:600px;margin:0 auto;background-color:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden;">
        <div style="background-color:#020617;padding:20px 28px;border-bottom:3px solid {color};">
          <span style="color:#e2e8f0;font-size:12px;letter-spacing:2px;text-transform:uppercase;">SOC Incident Alert</span>
          <h1 style="color:#f8fafc;font-size:20px;margin:8px 0 0 0;">{incident['title']}</h1>
        </div>
        <div style="padding:24px 28px;">
          <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
            <tr>
              <td style="padding:6px 0;color:#94a3b8;font-size:13px;width:120px;">Severity</td>
              <td style="padding:6px 0;">
                <span style="background-color:{color}22;color:{color};border:1px solid {color};padding:3px 12px;border-radius:999px;font-size:12px;font-weight:600;">{incident['severity']}</span>
              </td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Status</td>
              <td style="padding:6px 0;color:#e2e8f0;font-size:13px;">{incident['status']}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Affected Asset</td>
              <td style="padding:6px 0;color:#e2e8f0;font-size:13px;">{incident['asset']}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Reported By</td>
              <td style="padding:6px 0;color:#e2e8f0;font-size:13px;">{incident['reporter']}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Incident ID</td>
              <td style="padding:6px 0;color:#e2e8f0;font-size:12px;font-family:monospace;">{incident['id']}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Timestamp</td>
              <td style="padding:6px 0;color:#e2e8f0;font-size:13px;">{incident['created_at']}</td>
            </tr>
          </table>
          <div style="background-color:#0f172a;border:1px solid #334155;border-radius:8px;padding:16px;">
            <p style="color:#94a3b8;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px 0;">Description</p>
            <p style="color:#cbd5e1;font-size:14px;line-height:1.6;margin:0;">{incident['description']}</p>
          </div>
        </div>
        <div style="background-color:#020617;padding:14px 28px;">
          <p style="color:#64748b;font-size:11px;margin:0;">Automated alert dispatched by the SOC Incident Reporting &amp; Alerting Portal.</p>
        </div>
      </div>
    </div>
    """


def send_alert_email(incident):
    """
    Attempts to dispatch an HTML alert email using SendGrid if
    SENDGRID_API_KEY is configured, otherwise falls back to raw SMTP if
    SMTP_HOST is configured. Returns a dict describing the outcome; never
    raises, so incident creation always succeeds even if alerting fails.
    """
    recipient = os.environ.get("ALERT_RECIPIENT_EMAIL")
    if not recipient:
        return {"sent": False, "reason": "ALERT_RECIPIENT_EMAIL is not configured"}

    subject = f"[SOC ALERT - {incident['severity'].upper()}] {incident['title']}"
    html_content = _build_alert_html(incident)

    sendgrid_key = os.environ.get("SENDGRID_API_KEY")
    if sendgrid_key:
        return _send_via_sendgrid(sendgrid_key, recipient, subject, html_content)

    smtp_host = os.environ.get("SMTP_HOST")
    if smtp_host:
        return _send_via_smtp(recipient, subject, html_content)

    return {"sent": False, "reason": "No email provider configured (SENDGRID_API_KEY or SMTP_HOST)"}


def _send_via_sendgrid(api_key, recipient, subject, html_content):
    from_email = os.environ.get("ALERT_SENDER_EMAIL", "soc-alerts@example.com")
    payload = {
        "personalizations": [{"to": [{"email": recipient}]}],
        "from": {"email": from_email, "name": "SOC Incident Portal"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers=headers,
            data=json.dumps(payload),
            timeout=10,
        )
        if resp.status_code in (200, 201, 202):
            return {"sent": True, "provider": "sendgrid"}
        return {
            "sent": False,
            "provider": "sendgrid",
            "reason": f"SendGrid responded with status {resp.status_code}: {resp.text[:300]}",
        }
    except requests.RequestException as exc:
        return {"sent": False, "provider": "sendgrid", "reason": str(exc)}


def _send_via_smtp(recipient, subject, html_content):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("ALERT_SENDER_EMAIL", smtp_user or "soc-alerts@example.com")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = recipient
    message.attach(MIMEText("This alert requires an HTML-capable email client.", "plain"))
    message.attach(MIMEText(html_content, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls(context=context)
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_email, [recipient], message.as_string())
        return {"sent": True, "provider": "smtp"}
    except (smtplib.SMTPException, OSError) as exc:
        return {"sent": False, "provider": "smtp", "reason": str(exc)}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_incident_payload(payload, partial=False):
    errors = []
    required_fields = ["title", "description", "severity", "asset", "reporter"]

    if not partial:
        for field in required_fields:
            if not payload.get(field):
                errors.append(f"'{field}' is required")

    if "severity" in payload and payload["severity"] not in VALID_SEVERITIES:
        errors.append(f"'severity' must be one of {sorted(VALID_SEVERITIES)}")

    if "status" in payload and payload["status"] not in VALID_STATUSES:
        errors.append(f"'status' must be one of {sorted(VALID_STATUSES)}")

    return errors


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "time": datetime.now(timezone.utc).isoformat(),
            "email_provider_configured": bool(
                os.environ.get("SENDGRID_API_KEY") or os.environ.get("SMTP_HOST")
            ),
        }
    )


@app.route("/api/incidents", methods=["GET"])
def list_incidents():
    incidents = _load()

    severity = request.args.get("severity")
    status = request.args.get("status")
    search = request.args.get("search", "").strip().lower()

    if severity and severity != "All":
        incidents = [i for i in incidents if i["severity"] == severity]
    if status and status != "All":
        incidents = [i for i in incidents if i["status"] == status]
    if search:
        incidents = [
            i
            for i in incidents
            if search in i["title"].lower()
            or search in i["description"].lower()
            or search in i["asset"].lower()
        ]

    incidents.sort(key=lambda i: i["created_at"], reverse=True)
    return jsonify({"incidents": incidents, "count": len(incidents)})


@app.route("/api/incidents", methods=["POST"])
def create_incident():
    payload = request.get_json(silent=True) or {}
    errors = _validate_incident_payload(payload)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    now = datetime.now(timezone.utc).isoformat()
    incident = {
        "id": str(uuid.uuid4()),
        "title": payload["title"].strip(),
        "description": payload["description"].strip(),
        "severity": payload["severity"],
        "status": payload.get("status", "Open"),
        "reporter": payload["reporter"].strip(),
        "asset": payload["asset"].strip(),
        "created_at": now,
        "updated_at": now,
    }

    incidents = _load()
    incidents.append(incident)
    _save(incidents)

    alert_result = send_alert_email(incident)

    return (
        jsonify({"incident": incident, "alert": alert_result}),
        201,
    )


@app.route("/api/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    incidents = _load()
    incident = next((i for i in incidents if i["id"] == incident_id), None)
    if not incident:
        return jsonify({"error": "Incident not found"}), 404
    return jsonify({"incident": incident})


@app.route("/api/incidents/<incident_id>", methods=["PUT"])
def update_incident(incident_id):
    payload = request.get_json(silent=True) or {}
    errors = _validate_incident_payload(payload, partial=True)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    incidents = _load()
    index = next((idx for idx, i in enumerate(incidents) if i["id"] == incident_id), None)
    if index is None:
        return jsonify({"error": "Incident not found"}), 404

    editable_fields = ["title", "description", "severity", "status", "reporter", "asset"]
    for field in editable_fields:
        if field in payload:
            incidents[index][field] = payload[field]
    incidents[index]["updated_at"] = datetime.now(timezone.utc).isoformat()

    _save(incidents)
    return jsonify({"incident": incidents[index]})


@app.route("/api/incidents/<incident_id>", methods=["DELETE"])
def delete_incident(incident_id):
    incidents = _load()
    index = next((idx for idx, i in enumerate(incidents) if i["id"] == incident_id), None)
    if index is None:
        return jsonify({"error": "Incident not found"}), 404

    removed = incidents.pop(index)
    _save(incidents)
    return jsonify({"deleted": removed["id"]})


@app.route("/api/incidents/<incident_id>/alert", methods=["POST"])
def resend_alert(incident_id):
    incidents = _load()
    incident = next((i for i in incidents if i["id"] == incident_id), None)
    if not incident:
        return jsonify({"error": "Incident not found"}), 404

    alert_result = send_alert_email(incident)
    return jsonify({"alert": alert_result})


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(_e):
    return jsonify({"error": "Internal server error"}), 500


# Vercel's Python runtime looks for a WSGI-compatible callable named `app`.
if __name__ == "__main__":
    app.run(debug=True, port=5000)
