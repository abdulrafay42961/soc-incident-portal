# SOC Incident Reporting & Alerting Portal

A lightweight Security Operations Center (SOC) dashboard for logging security
incidents and automatically dispatching HTML email alerts. Built as a static
frontend backed by a Python serverless API, designed to deploy on Vercel with
zero configuration beyond environment variables.

## Architecture Overview

```
├── api/
│   └── index.py        # Flask app exposed as a Vercel Python serverless function.
│                        # Handles all /api/* routes: incident CRUD + email dispatch.
├── public/
│   ├── index.html       # Dark-theme dashboard UI (Tailwind via CDN, no build step).
│   └── app.js            # Vanilla JS: fetch-based API calls, DOM rendering, toasts.
├── vercel.json          # Routes /api/* to the Python function, everything else static.
├── requirements.txt     # Python dependencies for the serverless function.
└── .env.example         # Template for email provider credentials.
```

**Request flow:**

1. The browser loads `public/index.html` and `public/app.js` as static assets.
2. `app.js` calls `/api/incidents` (and related routes) using `fetch`.
3. `vercel.json` routes any request under `/api/*` to the Flask app in
   `api/index.py`, which Vercel runs as a Python serverless function.
4. On incident creation, the backend persists the record and calls
   `send_alert_email()`, which dispatches an HTML email via SendGrid (if
   `SENDGRID_API_KEY` is set) or raw SMTP (if `SMTP_HOST` is set).

**Storage note:** incidents are persisted to `/tmp/soc_incidents.json` inside
the serverless function's writable temp directory. This works well for demos
and light usage, but `/tmp` is only guaranteed to persist for the lifetime of
a single warm container — a cold start or traffic across multiple regions can
reset it. For production-grade persistence, swap the `_load` / `_save`
functions in `api/index.py` for a managed database such as Vercel Postgres,
Supabase, or PlanetScale.

## Features

- **Incident logging** — title, description, severity, status, affected
  asset, and reporter, validated server-side.
- **Live incident log** — auto-refreshes every 15 seconds, with severity
  filter chips, free-text search, and a detail modal for status updates.
- **Email alerts** — every new incident triggers an HTML-formatted alert
  email; alerts can also be manually re-sent from the detail modal.
- **Dark cyberpunk SOC theme** — slate (`#0f172a`) background, neon
  severity badges (cyan/amber/orange/red), monospace data readouts, subtle
  scanline and pulse animations.
- **Toast notifications** — success, warning, and error feedback for every
  action, including whether the alert email actually sent.

## Prerequisites

- A [GitHub](https://github.com) account.
- A [Vercel](https://vercel.com) account (the free Hobby tier is enough).
- One of the following for email alerts:
  - A [SendGrid](https://sendgrid.com) account and API key, **or**
  - SMTP credentials from your email provider (Gmail App Password, Mailgun,
    Amazon SES SMTP, Office 365, etc.).

## Local Development

```bash
git clone https://github.com/your-username/soc-incident-portal.git
cd soc-incident-portal

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your ALERT_RECIPIENT_EMAIL and either SENDGRID_API_KEY
# or SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD

python api/index.py
```

The Flask dev server starts on `http://localhost:5000`. Serve `public/` with
any static file server pointed at the same origin, or use the Vercel CLI
(below) to run the full stack (static + API) together.

### Running the full stack locally with the Vercel CLI (recommended)

```bash
npm install -g vercel
vercel dev
```

This serves `public/` and proxies `/api/*` to `api/index.py` exactly as it
will behave in production, and reads variables from your local `.env`.

## Deploying to GitHub + Vercel

### 1. Push the repository to GitHub

```bash
git init
git add .
git commit -m "Initial commit: SOC Incident Reporting & Alerting Portal"
git branch -M main
git remote add origin https://github.com/your-username/soc-incident-portal.git
git push -u origin main
```

### 2. Import the project into Vercel

1. Go to [vercel.com/new](https://vercel.com/new) and select your GitHub
   repository.
2. Vercel will auto-detect `vercel.json` — leave the build settings as
   default (no build command or output directory is needed; the static
   files in `public/` and the Python function in `api/` are picked up
   directly).
3. Under **Environment Variables**, add the variables from `.env.example`:
   - `ALERT_RECIPIENT_EMAIL`
   - `ALERT_SENDER_EMAIL`
   - `SENDGRID_API_KEY` **or** `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD`
4. Click **Deploy**.

### 3. Verify the deployment

Once deployed, visit your Vercel URL and:

- Confirm the top-right connection indicator shows **LINK ESTABLISHED**.
- Submit a test incident and confirm it appears in the log immediately.
- Check the recipient inbox configured in `ALERT_RECIPIENT_EMAIL` for the
  HTML alert email.
- Hit `https://your-deployment.vercel.app/api/health` directly — it should
  return `{"status": "ok", ...}` and confirm whether an email provider is
  configured.

## Configuring Email Alerts

### Option A — SendGrid

1. Create an API key in the SendGrid dashboard with **Mail Send** permission.
2. Verify a sender identity (single sender or domain authentication) — this
   becomes your `ALERT_SENDER_EMAIL`.
3. Set `SENDGRID_API_KEY` and `ALERT_SENDER_EMAIL` in your environment.

### Option B — SMTP

1. Gather your provider's SMTP host, port, username, and password (for
   Gmail, use an [App Password](https://myaccount.google.com/apppasswords)
   rather than your account password).
2. Set `SMTP_HOST`, `SMTP_PORT` (usually `587` for STARTTLS), `SMTP_USER`,
   `SMTP_PASSWORD`, and `ALERT_SENDER_EMAIL`.
3. Leave `SENDGRID_API_KEY` unset — the backend checks SendGrid first and
   falls back to SMTP automatically.

If neither provider is configured, incidents still log successfully; the API
response simply reports that no alert was sent, and the UI surfaces this as
a warning toast.

## API Reference

| Method | Route                       | Description                                  |
|--------|------------------------------|-----------------------------------------------|
| GET    | `/api/health`                | Health check and email-provider diagnostics  |
| GET    | `/api/incidents`             | List incidents (`?severity=`, `?status=`, `?search=`) |
| POST   | `/api/incidents`             | Create an incident and dispatch an alert     |
| GET    | `/api/incidents/<id>`        | Fetch a single incident                      |
| PUT    | `/api/incidents/<id>`        | Update fields on an incident (e.g. status)   |
| DELETE | `/api/incidents/<id>`        | Delete an incident                           |
| POST   | `/api/incidents/<id>/alert`  | Re-send the alert email for an incident      |

## Security Notes

- CORS is enabled broadly for demo convenience; restrict `Flask-Cors` to
  your production origin before exposing this publicly.
- There is no authentication layer in this starter — add one (e.g. Vercel
  Access, a reverse proxy with SSO, or API-key middleware in
  `api/index.py`) before using this for real incident data.
- Rotate `SENDGRID_API_KEY` / `SMTP_PASSWORD` immediately if they are ever
  committed to source control; `.env` is already covered by the
  `.gitignore` pattern below.

## Suggested `.gitignore`

```
.env
venv/
__pycache__/
*.pyc
.vercel/
```
