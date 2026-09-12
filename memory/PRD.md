# SAR Satellite Crop Flood Engine — PRD

## Original problem statement
Build the core working MVP of SAR Satellite Crop Flood Engine, prioritizing authentication, field management, PostGIS geometry, SAR flood analysis, map, history, and dashboard, followed by medium/final features. Requested stack: React + TypeScript + Vite, FastAPI, PostgreSQL + PostGIS, Docker Compose, docs, tests, secure uploads. No fake controls; DEMO/TEST data must be clearly labelled; PDF reports must carry a non-official insurance disclaimer.

## Architecture (current)
- Frontend: React (CRA/CRACO, JavaScript) + Leaflet/React-Leaflet. `App.js` dashboard, `Enhancements.js` field workbench, `FieldDrawMap.js` click-to-draw/drag-to-edit polygon editor, `SentinelTools.js` raster lab, `TrendSignals.js`.
- Backend: FastAPI (`server.py` routes) split into `engine.py` (pure deterministic logic), `storage.py` (PostgisStore canonical / MongoStore fallback), `raster.py` (rasterio change detection + DEMO raster), `sql/init.sql` schema, `scripts/ensure_local_postgis.sh` idempotent local bootstrap.
- Storage: **PostGIS canonical** when `POSTGIS_DATABASE_URL` is set (preview + Docker Compose). `fields.geom geometry(Polygon,4326)` + GIST; area from `ST_Area(geom::geography)`; analyses/sentinel_runs JSONB with FK cascade. MongoDB only if PostGIS unreachable (logged; `/api/health` returns 503 "degraded"). Never dual-write.
- Auth: JWT bearer (PyJWT) + bcrypt; roles farmer/admin; ownership checks on every field route.
- DEMO flood: deterministic waterbody covering the southern 55% of the field bbox ∩ field polygon (geodesic) → seeded field 55.2% HIGH. DEMO raster is generated over the field bbox with the same band → ~53.5%.

## Implemented
- 2026-02-01: Auth, field CRUD, area calculation, DEMO SAR analysis, flood map, dashboard, alerts, soil/weather panels, recommendations, readiness, device and seed API contracts, Docker/README, Swagger.
- 2026-09-07: Field workbench CRUD, exact WGS84 geodesic area, flood history bars, PDF evidence report with disclaimer, optional PostGIS sync.
- 2026-09-10: Sentinel-1 before/after GeoTIFF upload pipeline (rasterio/shapely), field clipping, PNG artifacts, PDF embeds, trend delta.
- 2026-09-12 (this iteration, testing-agent iteration_3 passed 40/40 backend + all UI flows):
  - PostGIS canonical persistence for users/fields/analyses/sentinel_runs with schema init, Mongo fallback, `/api/health`, local bootstrap script + supervisor program.
  - Leaflet field drawing: click to add vertex, drag to move, click vertex to remove, undo/clear, synced JSON textarea with validation; dashboard map uses the real field polygon and refreshes on field changes.
  - `engine.py` + `tests/test_engine.py` (area, polygon validity incl. self-intersection, flood %, severity boundaries, soil, crops, readiness, alerts) and `tests/test_storage_postgis.py` round-trip.
  - Raster hardening: NaN-safe previews, int-dtype uploads, unreadable GeoTIFF → 422, non-overlap → 422; realistic partial DEMO flood; artifact thumbnails fetched with auth (fixed double `/api` path bug).

## Backlog
- P1: Durable artifact storage (object storage / volume) — `backend/sentinel_results` is local disk.
- P1: Farmer registration UI; persisted soil/weather/crop history; live weather provider.
- P2: Vite + TypeScript frontend migration (bounded).
- P2: httpOnly cookie session instead of localStorage JWT; Random Forest artifact; seed image model; hardware ingestion.
