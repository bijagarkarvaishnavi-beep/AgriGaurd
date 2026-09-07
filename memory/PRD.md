# SAR Satellite Crop Flood Engine — PRD

## Original problem statement
Build the core working MVP of SAR Satellite Crop Flood Engine within 50 credits, prioritizing authentication, field management, PostGIS-ready geometry, SAR flood analysis, map, history, and dashboard, followed by medium/final features.

## Architecture decisions
- React starter frontend with Leaflet and a FastAPI API.
- Existing protected environment uses MongoDB; geometry is isolated as coordinate arrays for a future PostGIS adapter.
- JWT bearer sessions, bcrypt passwords, role field, and API validation.
- DEMO SAR/weather/soil data is explicit and never presented as real imagery.

## Personas and requirements
Farmers need a quick field-level flood decision; administrators need authenticated access and monitoring context. Core needs are field area, flood extent, severity, map, alerts, soil/weather context, crop recommendation, and readiness.

## Implemented (2026-02-01)
- Auth, field CRUD, area calculation, DEMO SAR analysis, flood map, dashboard, alerts, soil/weather panels, recommendations, readiness, device and seed API contracts, Docker/README, Swagger.

## Backlog
- P0: PostGIS geometry persistence and true raster Sentinel-1 processing.
- P1: persisted soil/weather/crop history, PDF evidence reports, farmer registration UI, flood history chart.
- P2: production weather provider, Random Forest training artifact, real seed image model, hardware ingestion.