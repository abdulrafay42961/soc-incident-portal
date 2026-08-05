# SOC Incident Notification & Alerting Portal

A full-featured Security Operations Center dashboard — incident intake form,
live incident/email logs, reports, audit trail, and settings — backed by a
single Flask app, ready to deploy on Vercel.

## Key behavior: who receives the alert

The person filling out the incident form types the **recipient's email
address** directly into the "Recipient email" field (along with a recipient
role: HR / Team Lead / CISO). Every alert email is sent to **that** address —
there is no fixed, hard-coded recipient. `.env` / Vercel environment
variables only configure the SMTP **sending** account, never the recipient.

## Architecture

```
├── api/
│   ├── index.py                  # Flask app — all routes, incident logic, email dispatch
│   └── templates/
│       ├── index.html            # Full dashboard UI (served at "/")
│       └── email_template.html   # HTML template used for outgoing alert emails
├── vercel.json                   # Routes every request to the Flask function
├── requirements.txt              # Python dependencies
└── .env.example                  # SMTP sender credential template
```

`vercel.json` rewrites every request path to the single Python function at
`api/index.py`. Flask's own routing then decides what to do: `/` renders
`index.html`, and `/api/incidents`, `/api/emails`, `/api/stats`,
`/api/settings`, `/api/health` return JSON.

**Storage note:** incident and email history are persisted to
`/tmp/soc_state.json` inside the serverless function's writable temp
directory, and evidence file attachments are staged in `/tmp/soc_uploads`
before being emailed and deleted. This survives repeated requests on a warm
container but resets on a cold start. For guaranteed durability, replace
`_load_state()` / `_save_state()` in `api/index.py` with a real database
(Vercel Postgres, Supabase, etc.).

## Local Development

```bash
git clone https://github.com/your-username/soc-incident-portal.git
cd soc-incident-portal

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD

python api/index.py
```

Visit `http://localhost:5000`.

## Deploying to GitHub + Vercel

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: SOC Incident Notification & Alerting Portal"
git branch -M main
git remote add origin https://github.com/your-username/soc-incident-portal.git
git push -u origin main
```

Make sure `api/`, `vercel.json`, `requirements.txt`, and `.env.example` sit
directly at the **repository root** — not nested inside another folder.

### 2. Import into Vercel

1. Go to [vercel.com/new](https://vercel.com/new) and select the repository.
2. **Root Directory** should be left blank (the repo root).
3. **Framework Preset**: "Other".
4. Under **Environment Variables**, add:
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `SMTP_USE_TLS` (optional, defaults to `true`)
   - `ALERT_SENDER_NAME` (optional)
5. Click **Deploy**.

### 3. Verify

- Visit `https://your-deployment.vercel.app/` — the dashboard should load.
- Hit `https://your-deployment.vercel.app/api/health` — should return
  `{"status": "ok", ...}`.
- Submit a test incident, typing **your own email** into the "Recipient
  email" field, and confirm the alert arrives there.
- Check `/api/settings` to confirm `smtp_configured` is `true`.

## Getting SMTP Credentials

### Gmail

1. Turn on 2-Step Verification: [myaccount.google.com/security](https://myaccount.google.com/security)
2. Generate an App Password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Set `SMTP_USERNAME` to your Gmail address and `SMTP_PASSWORD` to the
   16-character App Password (no spaces).

### SendGrid

1. Create an API key with **Mail Send** permission.
2. Set `SMTP_HOST=smtp.sendgrid.net`, `SMTP_USERNAME=apikey`, and
   `SMTP_PASSWORD=<your API key>`.
3. Verify a sender identity in SendGrid matching the address you send from.

## Security Notes

- There is no authentication on the API routes themselves (the in-app "sign
  in" is just a display-name prompt stored in the browser, not real auth).
  Add proper authentication before using this with real incident data.
- Rotate `SMTP_PASSWORD` immediately if it's ever committed to source
  control.
- Uploaded evidence files are deleted immediately after the email is sent or
  fails; they are never persisted long-term.
