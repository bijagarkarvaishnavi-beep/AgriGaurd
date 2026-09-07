# SAR Satellite Crop Flood Engine

A working high-priority MVP for field flood monitoring. It includes JWT farmer/admin access, field polygons, area calculations, modular DEMO SAR flood analysis, map visualization, alerts, soil/weather context, crop recommendation, and planting readiness.

## Run locally
1. Copy `backend/.env.example` to `backend/.env` and set a local JWT secret.
2. Ensure MongoDB is running, or use `docker compose up --build`.
3. In `frontend`, run `yarn start`.
4. Open `http://localhost:3000`. Demo admin: `admin@example.com` / `admin123`.

MongoDB remains the resilient local fallback, while Docker Compose now includes PostgreSQL/PostGIS. Set `POSTGIS_DATABASE_URL` to enable field geometry sync into a WGS84 `geography(POLYGON,4326)` column; area is calculated with exact WGS84 geodesics and mirrored to PostGIS when available.

## API
FastAPI Swagger is available at `http://localhost:8001/docs`. Key routes: `/api/auth/*`, `/api/fields`, `/api/flood/analyze`, `/api/fields/{field_id}/analyses`, `/api/fields/{field_id}/report`, `/api/dashboard`, `/api/devices/register`, and `/api/seed/*`.

The dashboard field workbench supports create/edit/delete, saved flood-percentage history bars, and PDF download. Reports are insurance-supporting evidence only and explicitly **NOT official insurance assessments**.

All SAR/weather/soil values are clearly labelled DEMO/TEST or ESTIMATED and must not be treated as official satellite, agronomic, or insurance assessments.
