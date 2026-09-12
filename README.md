# SAR Satellite Crop Flood Engine

A working high-priority MVP for field flood monitoring. It includes JWT farmer/admin access, field polygons, area calculations, modular DEMO SAR flood analysis, map visualization, alerts, soil/weather context, crop recommendation, and planting readiness.

## Run locally
1. Copy `backend/.env.example` to `backend/.env` and set a local JWT secret.
2. Ensure MongoDB is running, or use `docker compose up --build`.
3. In `frontend`, run `yarn start`.
4. Open `http://localhost:3000`. Demo admin: `admin@example.com` / `admin123`.

## Storage
PostgreSQL/PostGIS is the **canonical** datastore when `POSTGIS_DATABASE_URL` is set (Docker Compose wires this automatically). Schema lives in `backend/sql/init.sql` and is applied idempotently at startup: users, `fields` with `geometry(Polygon,4326)` + GIST index, `analyses` and `sentinel_runs` (JSONB, cascading on field delete). Field area is read from `ST_Area(geom::geography)`; polygons are validated (WGS84 range + no self-intersection) before insert. If PostGIS is unreachable the API logs a warning and runs entirely on MongoDB (`MONGO_URL`) — never both at once. `GET /api/` reports the active backend (`storage`).

## Tests
```
cd backend && REACT_APP_BACKEND_URL=http://localhost:8001 python -m pytest tests -q
```
`tests/test_engine.py` covers the deterministic engine (geodesic area, polygon validation, flood %, severity thresholds, soil, crops, readiness, alerts); `tests/test_storage_postgis.py` is a PostGIS round-trip (skipped without `POSTGIS_DATABASE_URL`); `tests/test_mvp_api.py` is the HTTP regression.

## API
FastAPI Swagger is available at `http://localhost:8001/docs`. Key routes: `/api/auth/*`, `/api/fields`, `/api/flood/analyze`, `/api/fields/{field_id}/analyses`, `/api/fields/{field_id}/report`, `/api/dashboard`, `/api/devices/register`, and `/api/seed/*`.

The dashboard field workbench supports drawing a field boundary directly on the Leaflet map (click to add vertices, drag to move, click a vertex to remove, undo/clear) with a synced JSON coordinate editor for keyboard entry, create/edit/delete, saved flood-percentage history bars coloured by severity, and PDF download. The DEMO flood scenario is a deterministic waterbody covering the southern 55% of the field's bounding box, intersected with the field polygon (geodesic), so results are partial and repeatable rather than 0% or 100%. Reports are insurance-supporting evidence only and explicitly **NOT official insurance assessments**.

All SAR/weather/soil values are clearly labelled DEMO/TEST or ESTIMATED and must not be treated as official satellite, agronomic, or insurance assessments.
