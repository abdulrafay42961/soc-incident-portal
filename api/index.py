import os
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def parse_cors_origins() -> Optional[Union[List[str], str]]:
    raw_origins = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw_origins or raw_origins == "*":
        return "*"
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


CORS(
    app,
    resources={r"/api/*": {"origins": parse_cors_origins()}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Type", "Authorization"],
)

incidents_db: List[Dict[str, Any]] = []
next_incident_id = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_incident(payload: Dict[str, Any]) -> Dict[str, Any]:
    global next_incident_id

    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    severity = str(payload.get("severity", "medium")).strip().lower() or "medium"
    source = str(payload.get("source", "portal")).strip() or "portal"
    status = str(payload.get("status", "open")).strip().lower() or "open"

    if not title or not description:
        raise ValueError("title and description are required")

    incident = {
        "id": f"INC-{next_incident_id:03d}",
        "title": title,
        "description": description,
        "severity": severity,
        "source": source,
        "status": status,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "tracking_id": str(uuid.uuid4())[:8],
    }

    incidents_db.append(incident)
    next_incident_id += 1
    return incident


def send_alert_email(incident: Dict[str, Any]) -> Dict[str, Any]:
    recipients = [recipient.strip() for recipient in os.getenv("ALERT_RECIPIENTS", "").split(",") if recipient.strip()]
    if not recipients:
        return {"status": "skipped", "reason": "No alert recipients configured"}

    from_email = os.getenv("SENDGRID_FROM_EMAIL") or os.getenv("SMTP_FROM_EMAIL") or "alerts@example.com"
    subject = f"[{incident['severity'].upper()}] {incident['title']}"
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #111827;">
        <h2>Security Alert Dispatched</h2>
        <p>A new incident has been reported in the SOC portal.</p>
        <ul>
          <li><strong>ID:</strong> {incident['id']}</li>
          <li><strong>Title:</strong> {incident['title']}</li>
          <li><strong>Severity:</strong> {incident['severity']}</li>
          <li><strong>Status:</strong> {incident['status']}</li>
          <li><strong>Source:</strong> {incident['source']}</li>
          <li><strong>Created:</strong> {incident['created_at']}</li>
        </ul>
        <p><strong>Description:</strong> {incident['description']}</p>
        <p>Review the incident in the portal immediately and assign an analyst.</p>
      </body>
    </html>
    """

    sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if sendgrid_api_key:
        try:
            message = Mail(
                from_email=from_email,
                to_emails=recipients,
                subject=subject,
                html_content=html_content,
            )
            sg = SendGridAPIClient(sendgrid_api_key)
            sg.send(message)
            return {"status": "sent", "provider": "sendgrid"}
        except Exception as exc:  # pragma: no cover - runtime fallback behavior
            return {"status": "failed", "provider": "sendgrid", "error": str(exc)}

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if smtp_host:
        try:
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_username = os.getenv("SMTP_USERNAME", "").strip()
            smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
            use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() == "true"

            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = from_email
            message["To"] = ", ".join(recipients)
            message.set_content("Please view the HTML version of this email.")
            message.add_alternative(html_content, subtype="html")

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if use_tls:
                    server.starttls()
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.send_message(message, from_addr=from_email, to_addrs=recipients)

            return {"status": "sent", "provider": "smtp"}
        except Exception as exc:  # pragma: no cover - runtime fallback behavior
            return {"status": "failed", "provider": "smtp", "error": str(exc)}

    return {"status": "skipped", "reason": "No email provider configured"}


@app.get("/api/incidents")
def list_incidents():
    return jsonify({"incidents": incidents_db, "count": len(incidents_db)}), 200


@app.post("/api/incidents")
def create_incident_route():
    payload = request.get_json(silent=True) or {}
    try:
        incident = create_incident(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    email_result = send_alert_email(incident)
    return jsonify({"incident": incident, "email": email_result}), 201


@app.get("/api/incidents/<incident_id>")
def get_incident(incident_id: str):
    incident = next((item for item in incidents_db if item["id"] == incident_id), None)
    if not incident:
        return jsonify({"error": "incident not found"}), 404
    return jsonify({"incident": incident}), 200


@app.delete("/api/incidents/<incident_id>")
def delete_incident(incident_id: str):
    global incidents_db
    incident = next((item for item in incidents_db if item["id"] == incident_id), None)
    if not incident:
        return jsonify({"error": "incident not found"}), 404

    incidents_db = [item for item in incidents_db if item["id"] != incident_id]
    return jsonify({"message": "incident deleted", "deleted_id": incident_id}), 200


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"}), 200


@app.get("/")
def index():
    return jsonify(
        {
            "message": "SOC Incident Reporting Portal API",
            "endpoints": ["/api/incidents", "/api/incidents/<id>"],
        }
    ), 200


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
