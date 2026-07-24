# AERP — Delivery Roadmap

Each phase is a coherent, testable slice. The guiding rule: **no fake data ever
ships**. When an engine can't compute a real value, it stores `NULL` and the API
surfaces "insufficient data" — it never fabricates.

| Phase | Deliverable | Status |
|------:|-------------|--------|
| 1 | **Backend foundation** — normalized DB schema, migrations, config, Docker Compose (Postgres/Redis), FastAPI skeleton, market + security seed, read-only screener endpoint. | ✅ Done |
| 2 | **Ingestion engine** — provider abstraction with fallback chain (per-market routing across FMP / TwelveData / Binance / PSX), Celery tasks + Beat schedule, universe loader, quote + daily-OHLC ingestion, admin trigger endpoints. Kills fake data; populates the real universe. | ✅ Done |
| 3 | **Fundamental engine** — 25+ ratios, Piotroski F-Score, Altman Z-Score, and an explainable weighted 0–100 score from stored statements (persisted to `financial_ratios`, `fundamental_snapshots`, `scores`). | ✅ Done |
| 4 | **Technical engine** — pure-NumPy EMA/SMA/MACD/RSI/ADX/ATR/SuperTrend/Ichimoku/VWAP/OBV/MFI/Bollinger/Keltner/Donchian + momentum/volatility/breakout + explainable 0–100 score, persisted to `technical_indicators` and `scores`. | ✅ Done |
| 5 | **Pattern detection** — swing pivots + candlestick, classic chart (double top/bottom, H&S, triangles, flags, cup & handle), and harmonic (Gartley/Bat/Butterfly/Crab/ABCD) patterns with confidence + target levels; surfaced as `top_pattern` in the screener. Elliott/Wyckoff omitted (not faked). | ✅ Done |
| 6 | **Composite scoring + signals** — 35% fundamental / 35% technical / 10% momentum / 10% quality / 10% risk blended into an explainable 0–100 composite, with buy/sell signals + rationale; fills `composite_score`, `signal` in the screener. | ✅ Done |
| 7 | **Frontend screener** — React + TS + Vite + Tailwind + AG Grid (infinite row model → server pagination), dark institutional theme, server sort/filter, column pinning, CSV export (full filtered set), saved views. | ✅ Done |
| 8 | **Company page** — `/company/{symbol}` API aggregating profile, quote, scores+breakdown, statements, ratios, technicals, active patterns, score history, peers, dividends, estimates + a rule-based AI summary; React page with TradingView chart, score cards, statements/technicals/patterns/valuation tabs, composite-history sparkline, peers. | ✅ Done |
| 9 | **Live prices** — SSE endpoint streaming the Redis `quotes` pub/sub channel (heartbeats, optional symbol filter); browser EventSource updates loaded grid rows in place (cell flash + LIVE badge) and the company header. | ✅ Done |
| 10 | **Auth, rate limiting, CI/CD, deploy** — JWT register/login/me, superuser-protected admin endpoints, per-user watchlists, Redis fixed-window rate limiting (fail-open), first-superuser bootstrap, backend + frontend CI, and the finalized Render/Docker blueprint. | ✅ Done |

## Data strategy — FREE, KEYLESS (no API keys required)

The default routing uses only free sources. The platform's symbols are already in
Yahoo Finance format, so `yfinance` is the universal provider.

| Market | Prices | Fundamentals | Source |
|--------|--------|--------------|--------|
| US (NYSE/NASDAQ/AMEX) | ✅ | ✅ statements | yfinance |
| India (NSE/BSE) | ✅ | ✅ statements | yfinance (`.NS`/`.BO`) |
| GCC (Tadawul/DFM/ADX) | ✅ (Tadawul best) | ⚠️ patchy | yfinance (`.SR` etc.) |
| **PSX (Pakistan)** | ✅ | ✅ **statements from CSV** | PSX portal + stockanalysis.com CSVs (site fallback) |
| **Forex** | ✅ | ✅ **macro** (GDP/CPI/rates) | yfinance + World Bank (keyless) |
| Commodities | ✅ | none (by design) | yfinance (`=F`) |
| Crypto | ✅ real-time | none (by design) | Binance (yfinance fallback) |

**Insider transactions:** US via SEC EDGAR Form 4 (keyless, live). **PSX** via a
CSV of director/insider dealings (Sarmaaya/PSX have no public API — a Playwright
scraper `scripts/scrape_psx_insider.py` produces the CSV, `AERP_PSX_INSIDER_CSV`);
both feed the same market-agnostic insider engine (60-day buy/sell score).

**Fundamentals by asset class:** equities (incl. PSX) → financial statements →
ratios/Piotroski/Altman → 0–100 score. **Forex** → country macro strength
differential (base vs quote) → 0–100 score. **Crypto & commodities** → no
fundamentals (technical-only composite). PSX statements come from the
stockanalysis.com CSV folder (`AERP_PSX_CSV_DIR`); refresh it with
`scripts/scrape_psx.py` (optional, needs Playwright).

Caveats of free data: Yahoo is unofficial and may rate-limit datacenter IPs, and
statement row-labels can shift; every call is guarded and yields nothing (never a
fake) on failure. Some GCC/PSX fundamentals are thin.

The provider layer stays pluggable (`app/ingestion/providers/base.py`). Paid
providers (FMP, TwelveData, EODHD) remain in the codebase as **optional drop-ins**
but are **not wired into the default routing**, so no keys are needed to run.
