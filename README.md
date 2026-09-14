# Khet AI MVP

Run `python3 app.py`, then open `http://localhost:8000`. The application serves the dashboard and its API from one origin.

## Deployment Options

### Option 1: Render (Recommended for Full Backend + Frontend)
1. Push this repository to GitHub / GitLab.
2. Log into [Render](https://render.com) and click **New +** -> **Web Service**.
3. Select your repository.
4. Render will automatically detect `render.yaml` or you can manually set:
   - **Environment**: Python
   - **Build Command**: (leave empty)
   - **Start Command**: `python3 app.py`
5. Click **Create Web Service**. Your persistent API & dashboard UI will be live!

### Option 2: Vercel (Static Dashboard & Serverless API)
1. Push this repository to GitHub.
2. Import the project in [Vercel](https://vercel.com).
3. Vercel automatically reads `vercel.json` and routes `/` to `outputs/index.html` and `/api/*` to `api/index.py`.

### Option 3: Docker / Container Platforms (Railway, Cloud Run, AWS)
Build and run using Docker:
```bash
docker build -t khetai .
docker run -p 8000:8000 khetai
```

---

## What is implemented

- SQLite-backed farm digital twin: farms, fields, observations, recommendations, alerts and audit log.
- Farm onboarding API with fields, location and crop context.
- Weather connector using Open-Meteo (no API key). It ingests a farm-specific forecast and evaluates rules.
- Generic satellite/sensor/partner ingestion webhook. A Sentinel/STAC or IoT connector can POST normalized observations without changing the decision model.
- Deterministic crop-risk rules for irrigation, humidity-related tomato inspection, and satellite vigour anomalies.
- Recommendation provenance, confidence, urgency and human approval state.
- In-app alert records. WhatsApp, SMS, IVR and irrigation-controller adapters should be implemented with a provider account and explicit farmer consent.

## API examples

`GET /api/health` · `GET /api/farms` · `GET /api/farms/1/twin` · `GET /api/farms/1/recommendations`

`POST /api/farms/1/refresh-weather` refreshes Open-Meteo data. `POST /api/farms/1/evaluate` runs the crop rules. `POST /api/recommendations/1` approves a recommendation. `POST /api/ingest/observation` receives a normalized weather, sensor or satellite observation.

Example observation body:

```json
{"farm_id":1,"field_id":1,"source":"satellite","kind":"vegetation","provider":"sentinel_processor","payload":{"ndvi":0.58,"baseline_ndvi":0.67,"anomaly":"west zone decline"}}
```

This is an MVP, not agricultural advice or a chemical/irrigation control system. Production deployment needs authenticated users, consent, encryption, provider contracts, agronomist validation, alert delivery adapters, rate limiting, monitoring and regulatory review.
