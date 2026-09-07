# SAR Satellite Crop Flood Engine

A working high-priority MVP for field flood monitoring. It includes JWT farmer/admin access, field polygons, area calculations, modular DEMO SAR flood analysis, map visualization, alerts, soil/weather context, crop recommendation, and planting readiness.

## Run locally
1. Copy `backend/.env.example` to `backend/.env` and set a local JWT secret.
2. Ensure MongoDB is running, or use `docker compose up --build`.
3. In `frontend`, run `yarn start`.
4. Open `http://localhost:3000`. Demo admin: `admin@example.com` / `admin123`.

The current starter environment is MongoDB-backed. Polygon coordinates are stored as GeoJSON-style arrays and area uses a small-farm planar approximation. A PostGIS adapter is the next database migration step; the API contract keeps geometry isolated for that change.

## API
FastAPI Swagger is available at `http://localhost:8001/docs`. Key routes: `/api/auth/*`, `/api/fields`, `/api/flood/analyze`, `/api/dashboard`, `/api/devices/register`, and `/api/seed/*`.

All SAR/weather/soil values are clearly labelled DEMO/TEST or ESTIMATED and must not be treated as official satellite, agronomic, or insurance assessments.
