# AERP — Architecture

## Principles

1. **The web tier is read-only.** FastAPI endpoints read from Postgres (and Redis
   cache). They never call an external data provider inline, so a slow or down
   provider can never degrade the user-facing API.
2. **Ingestion is asynchronous.** Celery workers fetch data on Beat schedules and
   persist it. Providers are behind an abstraction with an ordered fallback chain.
3. **No fabricated data.** If a value can't be computed or fetched, it is stored as
   `NULL`. The UI shows "insufficient data", never a placeholder number.
4. **Every score is explainable.** Scores are stored alongside a JSON breakdown of
   the inputs and weights that produced them.
5. **Secrets never reach the client.** API keys live only in backend env vars.

## Components

```
                         ┌────────────────────────────┐
   Browser (SPA)         │  FastAPI  (web dyno)        │
   AG Grid / TradingView │  - /screener  (read DB)     │
        │  SSE/WS         │  - /company   (read DB)     │
        └───────────────►│  - /prices    (SSE from Redis pubsub)
                         └──────────────┬─────────────┘
                                        │ read
                     ┌──────────────────▼───────────────────┐
                     │  PostgreSQL  (source of truth)        │
                     └──────────────────▲───────────────────┘
                                        │ write
        ┌───────────────────────────────┴───────────────────┐
        │  Celery workers                                     │
        │   - ingestion.* (universe, prices, fundamentals)   │
        │   - engines.*   (technical, fundamental, patterns) │
        │   - scoring.*   (composite, signals)               │
        └───────────────────────────────▲───────────────────┘
                                        │ schedule
                                ┌───────┴────────┐
                                │  Celery Beat   │
                                └────────────────┘

   Redis: result backend + broker + quote cache + SSE/WS pub-sub
```

## Data model (Phase 1)

Normalized schema, grouped by concern:

- **Reference:** `markets`, `securities`
- **Prices:** `daily_prices`, `intraday_prices`
- **Fundamentals:** `income_statements`, `balance_sheets`, `cash_flow_statements`,
  `financial_ratios`, `fundamental_snapshots`, `analyst_estimates`
- **Technical:** `technical_indicators`, `pattern_detections`
- **Corporate:** `corporate_actions`, `dividends`, `insider_transactions`
- **Market intel:** `news_articles`, `economic_events`
- **Analytics:** `scores`, `signals`
- **User:** `users`, `watchlists`, `watchlist_items`, `portfolios`,
  `portfolio_positions`

Indexing strategy: every foreign key is indexed; time-series tables carry a
composite unique index on `(security_id, date)` (and `timeframe`/`period` where
relevant) so upserts are idempotent and range scans are cheap.

## Environments

- **Local:** `infra/docker-compose.yml` — postgres, redis, api, worker, beat.
- **Production:** Render blueprint (`infra/render.yaml`) — managed Postgres +
  Redis, a web service, a worker, and a Beat scheduler. Frontend deploys as a
  static SPA (Render static site or GitHub Pages) — never as the backend.
