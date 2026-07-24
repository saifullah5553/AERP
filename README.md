# AERP — AI Equity Research Platform

A production-grade, multi-market equity research platform. Real prices, real
fundamental/technical analysis, real pattern detection — no random numbers, no
hardcoded scores.

**Coverage target:** PSX · US (NYSE/NASDAQ/AMEX) · India (NSE/BSE) · GCC · Forex ·
Commodities · Crypto — scaling to 20,000+ securities.

## Architecture

```
Frontend (React/TS/AG Grid/TradingView)  ──►  FastAPI (read-only, from DB/cache)
                                                   ▲
                        Redis (cache + pub/sub) ───┤
                                                   ▲
Celery Beat ─► Celery Workers ─► Ingestion ─► PostgreSQL
                 (providers: FMP · Binance · PSX · TwelveData · <paid>)
```

- **Web requests never call a data provider.** The API only reads Postgres/Redis.
- **Ingestion** runs on Celery Beat schedules and writes to Postgres.
- **Engines** (fundamental / technical / patterns / scoring) compute from stored
  data — every score is explainable and reproducible.
- **Secrets** live only in the backend environment. Nothing sensitive reaches the
  browser.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and
[`docs/ROADMAP.md`](docs/ROADMAP.md) for the phase plan.

## Repository layout

```
aerp/
├── backend/     # FastAPI · SQLAlchemy 2 · Celery · Alembic
├── frontend/    # React 18 · TypeScript · Vite · Tailwind · AG Grid
├── infra/       # docker-compose, Render blueprint
├── docs/        # architecture, roadmap
└── .github/     # CI + frontend deploy
```

## Frontend (Phase 7)

The screener is a professional AG Grid data table (dark institutional theme) using
the infinite row model backed by the API's server-side pagination/sort/filter —
so it scales to the full universe. Column pinning, full-filtered-set CSV export,
and localStorage saved views are included.

```bash
cd frontend
cp .env.example .env      # leave VITE_API_BASE empty for local dev
npm install
npm run dev               # http://localhost:5173 (proxies /api → :8000)
```

Run the backend (`docker compose -f infra/docker-compose.yml up`) alongside it,
then trigger ingestion + the engines (see below) to populate the grid.

## Quick start (Phase 1 — backend foundation)

Prerequisites: Docker Desktop.

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Then:

- API docs:      http://localhost:8000/docs
- Health:        http://localhost:8000/api/v1/health
- Markets:       http://localhost:8000/api/v1/markets
- Screener:      http://localhost:8000/api/v1/screener

The stack seeds reference markets and a small set of real securities on first
boot so the API returns data immediately.

### Ingestion (Phase 2)

Crypto (Binance) and PSX prices work with **no keys**. For US fundamentals/prices
and forex, add free keys to `.env` (`FMP_API_KEY`, `TWELVE_DATA_API_KEY`).

Celery Beat refreshes quotes/prices automatically, or trigger a run manually:

```bash
# Enqueue jobs (they run in the Celery worker, never in the web process):
curl -X POST "http://localhost:8000/api/v1/admin/ingest/quotes"
curl -X POST "http://localhost:8000/api/v1/admin/ingest/universe?providers=binance"
curl -X POST "http://localhost:8000/api/v1/admin/ingest/daily?region=global"
```

After a quote refresh, the screener's `price`/`change_pct` columns populate with
real data.

### Fundamentals & scores (Phase 3)

With an `FMP_API_KEY` set, ingest statements and compute the fundamental score
(every score carries a stored, auditable breakdown — no hardcoding):

```bash
curl -X POST "http://localhost:8000/api/v1/admin/ingest/fundamentals?region=us"
curl -X POST "http://localhost:8000/api/v1/admin/compute-fundamentals"
```

The screener's `fundamental_score`, `pe_ttm`, `roe`, `revenue_growth`, etc. then
populate.

### Technical scores (Phase 4)

After daily prices are ingested, compute indicators + the technical score
(explainable, from real OHLCV — no hardcoded ratings):

```bash
curl -X POST "http://localhost:8000/api/v1/admin/ingest/daily?region=us"
curl -X POST "http://localhost:8000/api/v1/admin/compute-technical"
```

`technical_score` then populates.

### Composite score & signals (Phase 6)

Blend everything into the final composite and derive buy/sell signals:

```bash
curl -X POST "http://localhost:8000/api/v1/admin/compute-composite"
```

`composite_score` (35% fundamental / 35% technical / 10% momentum / 10% quality /
10% risk) and `signal` now populate — each with a stored, explainable breakdown of
every component and its contribution.

To run migrations manually (they run automatically at container start):

```bash
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
```

## Development status

Phase 1 (backend foundation) is implemented. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for what each subsequent phase delivers.
