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
├── frontend/    # React 18 · TypeScript · Vite · Tailwind · AG Grid  (Phase 7)
├── infra/       # docker-compose, Render blueprint
├── docs/        # architecture, roadmap
└── .github/     # CI + frontend deploy
```

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
boot so the API returns data immediately. Full universe ingestion arrives in
Phase 2.

To run migrations manually (they run automatically at container start):

```bash
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
```

## Development status

Phase 1 (backend foundation) is implemented. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for what each subsequent phase delivers.
