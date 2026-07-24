# AERP — Deployment

## Local (Docker Compose)

```bash
cp .env.example .env            # fill provider keys + admin creds as desired
docker compose -f infra/docker-compose.yml up --build
```

Services: `postgres`, `redis`, `api` (runs migrations on boot), `worker`, `beat`.
API at http://localhost:8000/docs. Frontend: `cd frontend && npm install && npm run dev`.

## Production (Render blueprint)

`infra/render.yaml` provisions everything from one blueprint:

- **aerp-postgres** — managed Postgres
- **aerp-redis** — broker + cache + pub/sub
- **aerp-api** — FastAPI web service (Docker). Runs `alembic upgrade head` on start.
- **aerp-worker** — Celery worker
- **aerp-beat** — Celery Beat scheduler
- **aerp-frontend** — static SPA (Vite build)

Steps:

1. Push the repo to GitHub.
2. Render dashboard → **New → Blueprint** → point at `infra/render.yaml`.
3. Set the `sync: false` secrets in the dashboard:
   - `AERP_CORS_ORIGINS` = the deployed frontend URL
   - `AERP_ADMIN_EMAIL` / `AERP_ADMIN_PASSWORD` = first superuser (enables `/admin/ingest/*`)
   - Frontend `VITE_API_BASE` = the API service URL
   - (Data providers need no keys — ingestion is free/keyless via yfinance + Binance + PSX.)
4. Deploy. On first boot the API runs migrations, seeds reference data, and creates
   the superuser.

The frontend may alternatively be served from **GitHub Pages** (it is a static SPA);
GitHub Pages must only serve the built `frontend/dist`, never act as the backend.

## First data load

Authenticate as the superuser, then trigger ingestion + engines (or wait for Beat):

```bash
# obtain a token
curl -X POST "$API/api/v1/auth/login" -d "username=$ADMIN_EMAIL&password=$ADMIN_PASSWORD"
# then, with the bearer token:
curl -X POST "$API/api/v1/admin/ingest/universe?providers=binance"  -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/ingest/quotes"                       -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/ingest/daily?region=us"              -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/ingest/fundamentals?region=us"       -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/compute-fundamentals"                -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/compute-technical"                   -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/detect-patterns"                     -H "Authorization: Bearer $T"
curl -X POST "$API/api/v1/admin/compute-composite"                   -H "Authorization: Bearer $T"
```
