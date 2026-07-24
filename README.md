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
                 (free providers: yfinance · Binance · PSX)
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

## Run the whole pipeline locally (no Docker/Celery needed)

The management CLI runs ingestion + all engines directly against the database.
Point `DATABASE_URL` at SQLite for a keyless local run:

```bash
cd backend
export DATABASE_URL="sqlite+pysqlite:///./aerp.db"
export AERP_PSX_CSV_DIR="../data/psx_csv"     # your PSX statement CSVs
python -m app.cli all        # schema → seed → ingest (PSX CSV, macro, quotes,
                             # prices, fundamentals) → compute every engine
```

Individual steps: `init-db`, `seed`, `load-universe`, `load-us-universe`,
`ingest-psx`, `ingest-macro`, `ingest-psx-insider`, `ingest-insider`, `ingest-news`,
`ingest-quotes`, `backfill`, `ingest-fundamentals`, `compute`. (Live prices/
fundamentals via yfinance need a normal IP — datacenter IPs get rate-limited by
Yahoo.)

### Free data sources (all keyless)

| Data | Source |
|------|--------|
| Prices — US/India/GCC/forex/commodities | yfinance |
| Prices — crypto | Binance |
| Prices — PSX | PSX portal (`dps.psx.com.pk`) |
| US universe (~7k tickers + CIK) | SEC `company_tickers_exchange.json` |
| Fundamentals — US/India/GCC | yfinance |
| Fundamentals — PSX | stockanalysis.com CSVs (`scripts/scrape_psx.py`) |
| Fundamentals — forex (macro) | World Bank Indicators API |
| Insider — US | SEC EDGAR Form 4 |
| Insider — PSX | Portfolio360 (`scripts/scrape_psx_insider.py`) |
| News | Google News RSS |

A full real-data run loads **7,500+ securities** (US + PSX) and scores them.

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

### Ingestion (Phase 2) — 100% free, no API keys

All markets use free, keyless sources: **yfinance** (US/India/GCC equities +
fundamentals, forex, commodities, crypto — the platform's symbols are already in
Yahoo format), **Binance** (real-time crypto), and the **PSX portal** scrape.
Paid providers (FMP/TwelveData/EODHD) exist as optional drop-ins but are not
wired in, so nothing needs a key.

**Fundamentals differ by asset class:**
- **Equities** (US/India/GCC) → statements via yfinance.
- **PSX** → financial statements from stockanalysis.com CSVs in `AERP_PSX_CSV_DIR`
  (refresh with `scripts/scrape_psx.py`), scored by the same engine; a PSX-portal
  site scrape fills partial metrics as fallback.
- **Forex** → country macro strength (GDP growth, inflation, real rates,
  unemployment, current account) from the World Bank (keyless); the base−quote
  differential becomes the pair's fundamental score.
- **Crypto & commodities** → no fundamentals by design (technical-only composite).

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

Ingest statements (keyless, via yfinance) and compute the fundamental score
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

### Live prices (Phase 9)

The `refresh_quotes` ingestion task publishes each tick to the Redis `quotes`
channel. The API exposes it as Server-Sent Events at
`GET /api/v1/stream/quotes` (optional `?symbols=AAPL,BTC-USD` filter). The frontend
opens an `EventSource` and updates loaded grid rows in place (with a cell flash and
a **LIVE** badge) and the company header — no page reload.

To run migrations manually (they run automatically at container start):

```bash
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
```

### Auth (Phase 10)

JWT auth guards write operations. Register/login, then use the bearer token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"supersecret1"}'
```

Admin ingestion/compute endpoints require a **superuser** — set `AERP_ADMIN_EMAIL`
and `AERP_ADMIN_PASSWORD` in `.env` to bootstrap one on startup. Per-user
watchlists live under `/api/v1/watchlists`. A Redis-backed rate limiter
(`AERP_RATE_LIMIT_PER_MINUTE`, fail-open) protects the API. See
[`docs/DEPLOY.md`](docs/DEPLOY.md) for production deployment.

## Development status

Phase 1 (backend foundation) is implemented. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for what each subsequent phase delivers.
