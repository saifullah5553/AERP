# Handover — the state of AERP

Last updated 2026-08-22.

**Clone the repo.** It is the source of truth and everything is pushed. Four things do not
travel with it, and two of them matter — read this before assuming a clone is enough.

```bash
git clone https://github.com/saifullah5553/AERP.git
cd AERP/backend && python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cd ../frontend && npm install
```

---

## THE ONE URGENT THING

**The repository is 5.04 GB and GitHub's soft limit is 5 GB.** 1,040 of the last 1,244 commits
touched the snapshot: a 459 MB directory rewritten up to 48 times a day, every version kept
forever. We are using git as a database.

This is not a tidiness problem. It is the constraint that ends the free hosting, and it is
independent of every other item here. The fix is Cloudflare R2 (10 GB free, no egress fees):
the refresh writes the snapshot to a bucket instead of committing it, and the repo goes back
to holding code.

One thing to decide first, deliberately: today `git show <sha>:frontend/public/data/screener.json`
recovers any past day, and that has been genuinely useful for tracing what changed. R2 has
versioning but is not free-tier generous. Give that up on purpose, not by accident.

---

## What travels with the clone

| | size | why it is committed |
|---|---|---|
| `data/prices/*.json.gz` | 48 MB | daily closes for every listing and index; **now carries volume too** |
| `data/fundamentals_ttm/*.json.gz` | 14 MB | the distilled quarterly-TTM store — every score comes from this |
| `data/sectors/*.csv` | ~550 KB | resolved sectors, so nothing re-fetches them |
| `data/exclusions/*.txt` | ~90 KB | symbols we deliberately do not carry, with the evidence |
| `frontend/public/data/` | 459 MB | the published snapshot |

A clone can run scoring, valuation, technicals and divergences immediately. It cannot re-scrape
fundamentals — see below.

## What does NOT travel

**1. The scraped CSVs.** ~270 MB across `us_data/`, `india_data/`, `australia_data/`,
`tadawul_data/`, `dfm_data/`, `psx_raw_data/` at the repo root, gitignored. Only
`consolidate-fundamentals` reads them and the distilled store it produces IS committed, so you
need these only to re-scrape or re-consolidate.

**2. `data/ohlc/` — 1.1 GB of per-symbol OHLCV CSVs.** Local only. The committed pack now
carries volume, so the gap this used to leave in EFI divergences is closed.

**3. The project memories** — `~/.claude/projects/C--Users-Saif-Ullah-AERP/memory/`. Machine
local. Copy them or the next session starts cold.

**4. Node modules.** `npm install` in `frontend/`.

---

## Corrections to what this file used to say

Three claims here were wrong and cost real time before being caught:

- **"Node is not installed."** It is — v22.23.2. You can `npx tsc --noEmit` and
  `npm run build` locally, which turns a three-minute CI round trip into seconds. Two red
  builds were spent guessing at TypeScript errors that a local typecheck would have shown.
- **"The PSX portal disconnects for individual stocks."** It does not. A cold client fetches
  LUCK, MCB, OGDC and HUBC fine; roughly a hundred symbols in, the IP is put in cooldown and
  then *everything* fails, including symbols that had just worked. That is throttling, and it
  produced the exact symptom mistaken for a dead endpoint.
- **"Yahoo does not carry PSX."** It does. `LUCK.KA` returns 439.30 PKR through the price
  proxy. `refresh_technicals` still has `skip_regions=("psx",)`, written on the opposite
  assumption — worth revisiting, as it would give PSX bars a second source.

## Daily operation

- `refresh-data.yml` — every 30 min: prices (capped, stalest-first), regime, sector stats
- `daily-refresh.yml` — 22:15 UTC: PSX bars, indices, prices (uncapped), technicals, quality,
  news, journal, portfolio
- `fundamentals-refresh.yml`, `psx-fundamentals.yml`, `earnings-fundamentals.yml` — on new
  results: consolidate → apply → rescore
- `deploy-cloudflare.yml` — Pages + Worker, **skips** until the secrets exist (see CLOUDFLARE.md)

**`verify-freshness` is the post-condition.** 24 checks — prices and bars per market, score
coverage as a ratio, grade/score agreement, snapshot timestamps — and it exits non-zero. It
runs as its own job so a stale artifact turns the run red without blocking the deploy. It is
the only command in the pipeline allowed to fail, and it exists because everything else is
fail-open: 35 `|| true` guards and ~40 swallowed exceptions mean a broken step is skipped, the
export carries the old value forward, and the run reports success.

```bash
cd backend && python -m app.cli verify-freshness --out ../frontend/public/data
```

## Open items, in the order I would take them

1. **The 5.04 GB repo.** Above. Everything else can wait; this cannot.
2. **5,357 companies are behind on results** — psx 383, us 3,268, india 1,315, gcc 286,
   australia 75, dfm 30. Measured by AGE of the newest period held, not a calendar date;
   a naive cutoff wrongly called 1,430 Australian companies late when most report half-yearly.
   The scrapers now support `AERP_SYMBOLS` and `AERP_FORCE` and write to the right directory,
   so the refresh is possible — but at ~3 min/company it is an overnight job (~19 h for PSX
   alone, ~270 h for everything), not an inline one.
3. **`screener.json` is 22.9 MB** against Cloudflare's 25 MB per-file cap, and it is a brutal
   first load on a phone. Split it per market; that fixes both.
4. **`^KSE100` and `DFMGI.AE` still have no screener row.** The regime now falls back to the
   price pack so PSX and Dubai are not wrong in the meantime, but the database export still
   does not produce them and `load-markets` did not fix it.
5. **Sections 11–12 of the fundamental spec are half-implemented.** Banks, insurers and REITs
   get correct N/A handling and renormalisation, but NIM, CET1, NPL, combined ratio and FFO
   are not in our statement store, so the substitute metrics do not exist. Needs a data source,
   not code.
6. **mypy: 76 errors across 32 files.** Pre-existing, and the step is `continue-on-error`
   ("advisory in Phase 1; enforced from Phase 3"). A large debt behind a flag.
7. **Divergences are unvalidated.** Run them through `factor_backtest` before sizing anything:
   the last factor study found every technical input was a *negative* predictor over 60 days.

## Three habits worth keeping

**Check named companies, not aggregates.** Every real defect this week came from one ticker.
Emaar at 8× its market cap while the median read 0.97. JPMorgan at 61.6 labelled VERY STRONG —
and a third of the universe with it. Dubai published Bullish on a "breadth" signal that was
secretly our own average score. Medians looked healthy throughout.

**An absence is not an error, and this pipeline has no opinion about absences.** PSX bars
stopped for 19 days, the daily refresh was cancelled 99 runs in 100, Dubai never appeared on
the sector page at all. Nothing failed. Check `as_of` per market, and check that a metric
measures what its name claims — `verify-freshness` catches staleness, not a wrong definition.

**Read the CI error, do not infer it.** No token needed:

```bash
curl -s https://api.github.com/repos/saifullah5553/AERP/commits/$(git rev-parse HEAD)/check-runs
```

Follow the failing run's `annotations_url`. Job logs need auth; annotations do not.
