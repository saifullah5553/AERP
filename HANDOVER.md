# Handover — moving to another machine

**Short answer: clone the repo.** It is the source of truth, the working tree is clean and
everything is pushed. But four things this work depends on are NOT in the repo, and two of them
matter. Read this before assuming a clone is enough.

```bash
git clone https://github.com/saifullah5553/AERP.git
cd AERP/backend && python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

---

## What travels with the clone

| | size | why it is committed |
|---|---|---|
| `data/prices/*.json.gz` | 47 MB | daily closes for every listing **and every index**. This is why CI — and a fresh clone — can price anything at all. Close-only. |
| `data/fundamentals_ttm/*.json.gz` | 14 MB | the distilled quarterly-TTM store. Every fundamental score is computed from this. |
| `data/sectors/*.csv` | 548 KB | resolved sectors, so nothing re-fetches them. Sector routing in the valuation depends on these. |
| `data/exclusions/*.txt` | 23 KB | symbols that file nothing, with the date and evidence for each. |
| `frontend/public/data/` | ~400 MB | the published snapshot itself. |

A clone can therefore run the **scoring, valuation, technical and divergence** passes
immediately. It cannot run a **fundamentals re-scrape** — see below.

## What does NOT travel, and what breaks without it

**1. The scraped CSVs — the fundamentals source.** ~270 MB across five folders in the Windows
user profile, gitignored deliberately:

```
C:\Users\Saif.Ullah\us_data          21,717 files   164 MB
C:\Users\Saif.Ullah\india_data        9,027 files    72 MB
C:\Users\Saif.Ullah\australia_data    5,056 files    25 MB
C:\Users\Saif.Ullah\tadawul_data      1,140 files   8.6 MB
C:\Users\Saif.Ullah\dfm_data            155 files   1.4 MB
```

Only `consolidate-fundamentals` reads them, and the distilled store it produces IS committed —
so you only need these if you want to re-scrape or re-consolidate. Copy them across, or re-run
the scrapers (`Stock Analysis CSV Data *.py`, also in the user profile, not the repo).

**2. `data/ohlc/` — 1.1 GB of per-symbol OHLCV CSVs.** Local only. The committed price pack
covers everything except **volume**, which matters in exactly one place: EFI divergences for
PSX read volume from this store and silently degrade to RSI-only without it. Everything else
(RSI divergences, structure, levels) works from the pack.

**3. The project memories** — `~/.claude/projects/C--Users-Saif-Ullah-AERP/memory/`. Machine
local. Copy that folder to the new machine or the next session starts without the accumulated
context. `aerp-verify-with-named-companies.md` is the one I would least want lost.

**4. Node is not installed here**, which is why every frontend change this session was
typechecked by CI rather than locally. **Install Node on the desktop** — it turns a three-minute
round trip into a one-second check and would have prevented two red builds.

---

## Daily operation

Everything auto-updates through GitHub Actions; nothing needs running by hand.

- `daily-refresh.yml` — prices (uncapped), technicals, divergences, quality, indices, portfolio
- `refresh-data.yml` — every 30 min: prices (capped, **stalest first**, so the cap rotates)
- `fundamentals-refresh.yml`, `psx-fundamentals.yml`, `earnings-fundamentals.yml` — on new
  results: consolidate → apply → **rescore** (that last step is what makes a new quarter reach
  the published scores and the DCF)

## Open items, in the order I would take them

1. **PSX `signal_since` is silently dead.** `_fetch_psx_history` returns `None` for every
   symbol — the portal serves `/timeseries/eod/KSE100` but disconnects for individual stocks.
   It fails closed, so nothing errors. Fix the same way the divergences were fixed: read from
   `ohlc_store` instead of the portal.
2. **117 US symbols** unresolved from rate limits — in the universe, unscored, not excluded.
3. **387 India sectors** missing; Yahoo's search returns nothing for those SME-board tickers.
4. **1,271 wide-spread and 270 single-method valuations** — labelled `unrated`, data-limited
   rather than broken.
5. **Divergences are unvalidated.** Run them through `factor_backtest` before sizing anything:
   the last factor study found every technical input was a *negative* predictor over 60 days.

## Two habits worth keeping

**Check named companies, not aggregates.** Every real defect this session came from a specific
ticker — Emaar at 8× market cap while the median read 0.97; PSX losing three quarters of its
scores while total coverage still showed 88%. Re-check the names raised earlier after any
change: Emaar silently reverted to its broken value two commits after being fixed.

**Read the CI error, do not infer it.** No token needed:

```bash
curl -s https://api.github.com/repos/saifullah5553/AERP/commits/$(git rev-parse HEAD)/check-runs
```

Follow the failing run's `annotations_url` for the exact file, line and message.
