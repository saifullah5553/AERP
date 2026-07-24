# AERP — Delivery Roadmap

Each phase is a coherent, testable slice. The guiding rule: **no fake data ever
ships**. When an engine can't compute a real value, it stores `NULL` and the API
surfaces "insufficient data" — it never fabricates.

| Phase | Deliverable | Status |
|------:|-------------|--------|
| 1 | **Backend foundation** — normalized DB schema, migrations, config, Docker Compose (Postgres/Redis), FastAPI skeleton, market + security seed, read-only screener endpoint. | ✅ Done |
| 2 | **Ingestion engine** — provider abstraction with fallback chain (FMP → TwelveData → Binance → PSX scrape), Celery + Beat, universe loader, daily OHLC ingestion. Kills fake data; loads the real universe. | ⏳ Next |
| 3 | **Fundamental engine** — all ratios, Piotroski F, Altman Z, weighted 0–100 score computed from stored statements. | ◻ Planned |
| 4 | **Technical engine** — EMA/SMA/MACD/RSI/ADX/ATR/SuperTrend/Ichimoku/VWAP/OBV/MFI/Bollinger/Keltner/Donchian/RS + 0–100 score from OHLC. | ◻ Planned |
| 5 | **Pattern detection** — candlestick, classic chart, and harmonic patterns with confidence scores from real pivots. | ◻ Planned |
| 6 | **Composite scoring + signals** — 35% fundamental / 35% technical / 10% momentum / 10% quality / 10% risk, fully explainable. | ◻ Planned |
| 7 | **Frontend screener** — React + AG Grid data table (sort/filter/group/pin/export/saved views), dark institutional theme. | ◻ Planned |
| 8 | **Company page** — TradingView chart, statements, peers, historical scores, analyst estimates, news, AI summary. | ◻ Planned |
| 9 | **Live prices** — SSE/WebSocket push from Redis pub/sub. | ◻ Planned |
| 10 | **Auth, rate limiting, tests, CI/CD, Render deploy.** | ◻ Planned |

## Data strategy (current decision: free/freemium mix)

| Market | Prices | Fundamentals |
|--------|--------|--------------|
| US (NYSE/NASDAQ/AMEX) | FMP free / TwelveData | FMP free (good) |
| Crypto | Binance public API | N/A (on-chain metrics later) |
| PSX (Pakistan) | PSX portal (`dps.psx.com.pk`) | Scrape / paid provider needed |
| India (NSE/BSE) | TwelveData / provider | **Thin on free tier** |
| GCC (Tadawul/DFM/ADX) | Provider needed | **Thin on free tier** |
| Forex / Commodities | TwelveData / FMP | N/A |

The provider layer is pluggable (`app/ingestion/providers/base.py`). A single paid
provider such as **EODHD** (~$20–80/mo) can be dropped in to fill every gap above
without touching the engines or API — it just becomes the primary in the fallback
chain.
