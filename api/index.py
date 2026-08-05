"""
SOC Incident Notification & Alerting Portal
=============================================
Flask backend that accepts incident reports from the web form, validates them,
generates a unique Incident ID, and dispatches a formatted HTML alert email to
the recipient address that the person submitting the form typed in
(`recipient_email`) — NOT a fixed address from an environment variable.

This file is structured to run as a Vercel Python serverless function at
api/index.py. Flask's default template_folder ("templates") resolves
relative to this file's own directory, so templates live at
api/templates/index.html and api/templates/email_template.html.

Run locally:
    pip install -r requirements.txt
    export SMTP_HOST=smtp.gmail.com
    export SMTP_PORT=587
    export SMTP_USERNAME=your_soc_alerts@company.com
    export SMTP_PASSWORD=your_app_password
    python api/index.py

The app then serves on http://localhost:5000
"""

import json
import os
import re
import random
import smtplib
import mimetypes
from io import BytesIO
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from flask import Flask, request, jsonify, render_template, send_file, abort

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.colors import HexColor

# --------------------------------------------------------------------------- #
# App configuration
# --------------------------------------------------------------------------- #

app = Flask(__name__)

# Vercel's deployment filesystem is READ-ONLY except for /tmp. Uploaded
# evidence files are staged there temporarily before being attached to the
# outgoing email and then removed. Locally this also works fine since /tmp
# exists on Linux/macOS; on Windows it falls back to the OS temp directory.
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/tmp/soc_uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

# Where the incident/email logs are persisted between requests. /tmp persists
# for the lifetime of a warm serverless container, so this survives repeated
# requests during normal usage but resets on a cold start. For guaranteed
# durability across cold starts and multiple regions, swap this for a real
# database (Vercel Postgres, Supabase, etc.).
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/soc_state.json")

# --------------------------------------------------------------------------- #
# SMTP configuration
# --------------------------------------------------------------------------- #
# NOTE: Never hard-code real credentials. Supply these as environment
# variables in Vercel Project Settings -> Environment Variables. For
# SendGrid, set SMTP_HOST=smtp.sendgrid.net, SMTP_USERNAME="apikey", and
# SMTP_PASSWORD=<your SendGrid API key>.

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
ALERT_SENDER_NAME = os.environ.get("ALERT_SENDER_NAME", "SOC Alerting System")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

ATTACK_TYPES = {
    "phishing", "ransomware", "unauthorized_access", "malware_execution",
    "ddos", "data_exfiltration", "other",
}
SEVERITY_LEVELS = {"critical", "high", "medium", "low"}
REPORTER_ROLES = {"soc_analyst", "user"}
RECIPIENT_ROLES = {"hr", "team_lead", "ciso"}

SEVERITY_META = {
    "critical": {"color": "#dc2626", "bg": "#450a0a", "label": "CRITICAL"},
    "high":     {"color": "#ea580c", "bg": "#431407", "label": "HIGH"},
    "medium":   {"color": "#ca8a04", "bg": "#422006", "label": "MEDIUM"},
    "low":      {"color": "#16a34a", "bg": "#052e16", "label": "LOW"},
}

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --------------------------------------------------------------------------- #
# Persisted data stores
# --------------------------------------------------------------------------- #
# Loaded from /tmp on cold start (empty on the very first invocation of a
# fresh container), kept in memory for the container's lifetime, and written
# back to /tmp after every mutation so subsequent warm invocations see it.

INCIDENT_LOG: list = []   # every incident ever submitted
EMAIL_LOG: list = []      # every email dispatch attempt (sent or failed)


def _load_state() -> None:
    global INCIDENT_LOG, EMAIL_LOG
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        INCIDENT_LOG = data.get("incidents", [])
        EMAIL_LOG = data.get("emails", [])
    except (json.JSONDecodeError, OSError):
        INCIDENT_LOG = []
        EMAIL_LOG = []


def _save_state() -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"incidents": INCIDENT_LOG, "emails": EMAIL_LOG}, f)
    except OSError:
        pass


_load_state()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def format_role(role: str) -> str:
    """Title-case a role slug while keeping known acronyms fully uppercase."""
    label = (role or "").replace("_", " ").title()
    for acronym in ("Soc", "Hr", "Ciso"):
        label = re.sub(rf"\b{acronym}\b", acronym.upper(), label)
    return label


def generate_incident_id() -> str:
    """Generate a unique incident ID, e.g. INC-2026-X892."""
    year = datetime.now().year
    letter = random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")  # skip ambiguous I/O
    digits = random.randint(100, 999)
    return f"INC-{year}-{letter}{digits}"


def validate_payload(data: dict) -> list:
    """Validate mandatory fields. Returns a list of human-readable errors."""
    errors = []

    required_text_fields = {
        "reporter_name": "Reporter name",
        "company_name": "Company name",
        "sender_email": "Sender email",
        "recipient_email": "Recipient email",
        "affected_assets": "Affected assets",
        "description": "Incident description",
    }
    for field, label in required_text_fields.items():
        if not data.get(field, "").strip():
            errors.append(f"{label} is required.")

    reporter_role = data.get("reporter_role", "").strip().lower()
    if reporter_role not in REPORTER_ROLES:
        errors.append("Reporter role must be 'SOC Analyst' or 'User'.")

    recipient_role = data.get("recipient_role", "").strip().lower()
    if recipient_role not in RECIPIENT_ROLES:
        errors.append("Recipient role must be 'HR', 'Team Lead', or 'CISO'.")

    attack_type = data.get("attack_type", "").strip().lower()
    if attack_type not in ATTACK_TYPES:
        errors.append("A valid attack type must be selected.")

    severity = data.get("severity", "").strip().lower()
    if severity not in SEVERITY_LEVELS:
        errors.append("A valid severity level must be selected.")

    sender_email = data.get("sender_email", "").strip()
    if sender_email and not EMAIL_REGEX.match(sender_email):
        errors.append("Sender email is not a valid email address.")

    recipient_email = data.get("recipient_email", "").strip()
    if recipient_email and not EMAIL_REGEX.match(recipient_email):
        errors.append("Recipient email is not a valid email address.")

    timestamp = data.get("timestamp", "").strip()
    if not timestamp:
        errors.append("Incident timestamp is required.")

    return errors


def build_email_html(incident: dict) -> str:
    """Render the HTML email template with incident details substituted in."""
    sev = SEVERITY_META[incident["severity"]]

    with open(os.path.join(app.root_path, "templates", "email_template.html"),
               "r", encoding="utf-8") as f:
        template = f.read()

    replacements = {
        "{{INCIDENT_ID}}": incident["incident_id"],
        "{{SEVERITY_LABEL}}": sev["label"],
        "{{SEVERITY_COLOR}}": sev["color"],
        "{{SEVERITY_BG}}": sev["bg"],
        "{{ATTACK_TYPE}}": incident["attack_type"].replace("_", " ").title(),
        "{{TIMESTAMP}}": incident["timestamp"],
        "{{REPORTER_NAME}}": incident["reporter_name"],
        "{{REPORTER_ROLE}}": format_role(incident["reporter_role"]),
        "{{COMPANY_NAME}}": incident["company_name"],
        "{{SENDER_EMAIL}}": incident["sender_email"],
        "{{AFFECTED_ASSETS}}": incident["affected_assets"],
        "{{DESCRIPTION}}": incident["description"].replace("\n", "<br>"),
        "{{RECIPIENT_ROLE}}": format_role(incident["recipient_role"]),
        "{{GENERATED_AT}}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def build_incident_pdf(incident: dict) -> bytes:
    """
    Render a plain, simple (white background / black text) PDF version of an
    incident report — used both for the live "Preview" in the form and for
    downloading a submitted incident later. `incident` may be a partial,
    not-yet-submitted draft (from the preview endpoint) or a fully saved
    record (from the history log) — every lookup below has a safe fallback
    so both cases render cleanly.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.85 * inch, bottomMargin=0.85 * inch,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
    )

    black = HexColor("#111111")
    gray = HexColor("#5a5a5a")

    title_style = ParagraphStyle(
        "ReportTitle", fontName="Helvetica", fontSize=22, leading=26,
        textColor=black, spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "ReportMeta", fontName="Helvetica", fontSize=10, leading=14,
        textColor=gray, spaceAfter=18,
    )
    label_style = ParagraphStyle(
        "Line", fontName="Helvetica", fontSize=11.5, leading=20,
        textColor=black, alignment=TA_LEFT,
    )
    section_gap = Spacer(1, 14)
    line_gap = Spacer(1, 4)

    def line(label: str, value: str):
        return Paragraph(f"<b>{label}:</b> {value or '—'}", label_style)

    severity = incident.get("severity", "").upper() or "—"
    attack_type = incident.get("attack_type", "").replace("_", " ").title() or "—"
    reporter_role = format_role(incident.get("reporter_role", ""))
    recipient_role = format_role(incident.get("recipient_role", ""))
    status = incident.get("email_status", "draft").replace("_", " ").title()
    generated_at = datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p")

    story = [
        Paragraph("SOC Incident Report", title_style),
        Paragraph(
            f"Incident ID: {incident.get('incident_id', 'DRAFT — not yet submitted')}",
            meta_style,
        ),

        # Reporter identity first, per request — name and role at the top.
        line("Reporter", f"{incident.get('reporter_name', '—')} ({reporter_role or '—'})"),
        line_gap,
        line("Company", incident.get("company_name", "—")),
        line_gap,
        line("Sender Email", incident.get("sender_email", "—")),
        section_gap,

        line("Incident Type", attack_type),
        line_gap,
        line("Severity", severity),
        line_gap,
        line("Affected Assets", incident.get("affected_assets", "—")),
        line_gap,
        line("Timestamp Detected", incident.get("timestamp", "—")),
        section_gap,

        Paragraph("<b>Description:</b>", label_style),
        line_gap,
        Paragraph((incident.get("description", "—") or "—").replace("\n", "<br/>"), label_style),
        section_gap,

        line("Routed To", f"{recipient_role or '—'} ({incident.get('recipient_email', '—')})"),
        section_gap,

        line("Status", status),
        line_gap,
        line("Generated", generated_at),
    ]

    doc.build(story)
    return buffer.getvalue()


def send_alert_email(incident: dict, attachment_path: str | None) -> None:
    """
    Compose and send the HTML alert email via SMTP to
    incident["recipient_email"] — the address the reporter typed into the
    form, not a fixed address from configuration.
    """
    sev = SEVERITY_META[incident["severity"]]

    msg = MIMEMultipart("mixed")
    msg["Subject"] = (f"[{sev['label']}] Security Incident {incident['incident_id']} "
                       f"- {incident['attack_type'].replace('_', ' ').title()}")
    msg["From"] = f"{ALERT_SENDER_NAME} <{SMTP_USERNAME or incident['sender_email']}>"
    msg["To"] = incident["recipient_email"]
    msg["Reply-To"] = incident["sender_email"]

    html_body = build_email_html(incident)
    msg.attach(MIMEText(html_body, "html"))

    if attachment_path and os.path.exists(attachment_path):
        ctype, _ = mimetypes.guess_type(attachment_path)
        ctype = ctype or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype=subtype)
            part.add_header(
                "Content-Disposition", "attachment",
                filename=os.path.basename(attachment_path),
            )
            msg.attach(part)

    if not SMTP_USERNAME or not SMTP_PASSWORD:
        # No SMTP credentials configured (e.g. local dev). Log instead of
        # raising, so the workflow is easy to test end-to-end.
        app.logger.warning(
            "SMTP_USERNAME/SMTP_PASSWORD not set - skipping real send. "
            "Email would have been sent to %s", incident["recipient_email"]
        )
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, [incident["recipient_email"]], msg.as_string())


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    """Serve the incident reporting form."""
    return render_template("index.html")


@app.route("/api/incidents", methods=["POST"])
def create_incident():
    """
    Accept a multipart/form-data submission containing incident fields and
    an optional evidence file, validate it, generate an Incident ID, and
    dispatch the alert email to the reporter-supplied recipient_email.
    """
    data = request.form.to_dict()
    errors = validate_payload(data)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    incident = {
        "incident_id": generate_incident_id(),
        "reporter_name": data["reporter_name"].strip(),
        "reporter_role": data["reporter_role"].strip().lower(),
        "company_name": data["company_name"].strip(),
        "sender_email": data["sender_email"].strip(),
        "recipient_role": data["recipient_role"].strip().lower(),
        "recipient_email": data["recipient_email"].strip(),
        "attack_type": data["attack_type"].strip().lower(),
        "severity": data["severity"].strip().lower(),
        "timestamp": data["timestamp"].strip(),
        "affected_assets": data["affected_assets"].strip(),
        "description": data["description"].strip(),
    }

    # Handle optional evidence attachment
    attachment_path = None
    uploaded_file = request.files.get("attachment")
    if uploaded_file and uploaded_file.filename:
        safe_name = f"{incident['incident_id']}_{uploaded_file.filename}".replace(" ", "_")
        attachment_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
        uploaded_file.save(attachment_path)

    created_at = datetime.now().isoformat()
    error_detail = None
    try:
        send_alert_email(incident, attachment_path)
        email_status = "sent"
    except Exception as exc:  # noqa: BLE001 - surface any SMTP failure to caller
        app.logger.error("Failed to send alert email: %s", exc)
        email_status = "failed"
        error_detail = str(exc)
    finally:
        # Clean up the staged file whether or not the send succeeded.
        if attachment_path and os.path.exists(attachment_path):
            os.remove(attachment_path)

    # Record the incident in the log for the Incidents view.
    incident_record = {**incident, "created_at": created_at, "email_status": email_status}
    INCIDENT_LOG.insert(0, incident_record)

    # Record the dispatch attempt in the log for the Email Center view.
    sev = SEVERITY_META[incident["severity"]]
    EMAIL_LOG.insert(0, {
        "incident_id": incident["incident_id"],
        "subject": (f"[{sev['label']}] Security Incident {incident['incident_id']} "
                    f"- {incident['attack_type'].replace('_', ' ').title()}"),
        "recipient_email": incident["recipient_email"],
        "recipient_role": incident["recipient_role"],
        "severity": incident["severity"],
        "status": email_status,
        "error_detail": error_detail,
        "sent_at": created_at,
    })

    _save_state()

    return jsonify({
        "success": True,
        "incident_id": incident["incident_id"],
        "severity": incident["severity"],
        "email_status": email_status,
    }), 201


@app.route("/api/incidents", methods=["GET"])
def list_incidents():
    """Return the full incident history, most recent first."""
    return jsonify({"incidents": INCIDENT_LOG})


@app.route("/api/incidents/preview-pdf", methods=["POST"])
def preview_incident_pdf():
    """
    Render whatever is currently typed into the incident form as a PDF —
    used for the live "Preview" panel. Does NOT save the incident and does
    NOT send an email; it only reads the submitted field values.
    """
    data = request.form.to_dict()
    draft = {
        "reporter_name": data.get("reporter_name", "").strip(),
        "reporter_role": data.get("reporter_role", "").strip().lower(),
        "company_name": data.get("company_name", "").strip(),
        "sender_email": data.get("sender_email", "").strip(),
        "recipient_role": data.get("recipient_role", "").strip().lower(),
        "recipient_email": data.get("recipient_email", "").strip(),
        "attack_type": data.get("attack_type", "").strip().lower(),
        "severity": data.get("severity", "").strip().lower(),
        "timestamp": data.get("timestamp", "").strip(),
        "affected_assets": data.get("affected_assets", "").strip(),
        "description": data.get("description", "").strip(),
    }
    pdf_bytes = build_incident_pdf(draft)
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name="incident-preview.pdf",
    )


@app.route("/api/incidents/<incident_id>/pdf", methods=["GET"])
def download_incident_pdf(incident_id):
    """Generate and return the PDF for an already-submitted incident."""
    incident = next((i for i in INCIDENT_LOG if i["incident_id"] == incident_id), None)
    if not incident:
        abort(404, description=f"Incident {incident_id} not found.")

    pdf_bytes = build_incident_pdf(incident)
    download = request.args.get("download") == "1"
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=download,
        download_name=f"{incident_id}.pdf",
    )


@app.route("/api/emails", methods=["GET"])
def list_emails():
    """Return the full outgoing-email history, most recent first."""
    return jsonify({"emails": EMAIL_LOG})


@app.route("/api/stats", methods=["GET"])
def stats():
    """Aggregated numbers for the dashboard cards and charts."""
    total = len(INCIDENT_LOG)
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    attack_counts: dict = {}
    timeline: dict = {}

    for inc in INCIDENT_LOG:
        severity_counts[inc["severity"]] = severity_counts.get(inc["severity"], 0) + 1
        attack_label = inc["attack_type"].replace("_", " ").title()
        attack_counts[attack_label] = attack_counts.get(attack_label, 0) + 1
        day = inc["created_at"][:10]
        timeline[day] = timeline.get(day, 0) + 1

    emails_sent = sum(1 for e in EMAIL_LOG if e["status"] == "sent")
    emails_failed = sum(1 for e in EMAIL_LOG if e["status"] == "failed")
    total_emails = len(EMAIL_LOG)
    success_rate = round((emails_sent / total_emails) * 100, 1) if total_emails else 100.0

    return jsonify({
        "total_incidents": total,
        "severity_counts": severity_counts,
        "attack_counts": attack_counts,
        "timeline": sorted(timeline.items()),
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
        "success_rate": success_rate,
        "recent_incidents": INCIDENT_LOG[:6],
    })


@app.route("/api/settings", methods=["GET"])
def settings():
    """Expose non-secret SMTP configuration for the Settings view."""
    return jsonify({
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
        "smtp_use_tls": SMTP_USE_TLS,
        "sender_name": ALERT_SENDER_NAME,
        "smtp_configured": bool(SMTP_USERNAME and SMTP_PASSWORD),
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
