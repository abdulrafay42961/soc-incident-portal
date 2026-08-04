# SOC Incident Reporting & Alerting Portal

A production-ready SOC incident reporting portal built with Flask for Vercel serverless deployment and a Tailwind-powered dark dashboard for incident intake and monitoring.

## Features

- In-memory incident storage for rapid prototyping and demos
- REST endpoints for listing, creating, reading, and deleting incidents
- Dynamic HTML email alerts through SendGrid or SMTP using environment variables
- CORS support for browser-based API access
- Cyberpunk-inspired dark UI with real-time incident filtering and table updates

## Local Development

1. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the environment example and configure your secrets:
   ```bash
   copy .env.example .env
   ```
4. Run the API locally:
   ```bash
   python api/index.py
   ```
5. Open the frontend at:
   ```text
   http://localhost:5000/
   ```

## Vercel Deployment

1. Push the project to GitHub.
2. Import it into Vercel.
3. Set the following environment variables in the Vercel dashboard:
   - `CORS_ORIGINS`
   - `ALERT_RECIPIENTS`
   - `SENDGRID_API_KEY` (optional if using SMTP)
   - `SENDGRID_FROM_EMAIL` (optional)
   - `SMTP_HOST` (optional if using SendGrid)
   - `SMTP_PORT`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `SMTP_FROM_EMAIL`
   - `SMTP_USE_TLS`
4. Deploy the project.

## API Endpoints

- `GET /api/incidents`
- `POST /api/incidents`
- `GET /api/incidents/<id>`
- `DELETE /api/incidents/<id>`
- `GET /health`
