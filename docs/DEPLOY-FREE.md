# Fully-free deployment

Two free options. **Option A works today with zero accounts and zero cost.**
Option B adds a real live backend (still free) for full interactivity.

## Option A — Auto-refreshing static site (already live, $0, no accounts)

- **Frontend:** GitHub Pages → https://saifullah5553.github.io/AERP/
- **"Backend":** the [`Refresh Demo Data`](../.github/workflows/refresh-data.yml)
  GitHub Actions workflow runs the full pipeline every 6 hours (free minutes),
  regenerates the real data snapshot (`frontend/public/data`), and commits it —
  which triggers [`Deploy Pages`](../.github/workflows/deploy-pages.yml) to
  republish. Self-updating, no server, no database.

Nothing to do — it's running. To refresh on demand: Actions tab → *Refresh Demo
Data* → *Run workflow*. To regenerate locally:

```bash
cd backend
DATABASE_URL="sqlite+pysqlite:///./aerp.db" AERP_PSX_CSV_DIR=../data/psx_csv \
AERP_PSX_INSIDER_CSV=../data/psx_insider.csv python -m app.cli all
python -m app.cli export-static     # writes frontend/public/data
```

Limitation: it's a periodic snapshot, so no real-time SSE/live-price tick and no
per-request interactivity. For that, use Option B.

## Option B — Fully-live backend (free tier, ~15 min setup)

Free building blocks:

| Piece | Free service |
|-------|--------------|
| Postgres | **Neon** (neon.tech) — persistent free tier |
| API (FastAPI) | **Render** free web service (Docker) |
| Data refresh | **GitHub Actions** cron (this repo) |
| Redis | *not needed* — the app fails open without it |
| Celery worker/beat | *not needed* — GitHub Actions is the scheduler |

### Steps

1. **Neon** → create a free project → copy the connection string
   (`postgresql://...`). This is your `DATABASE_URL`.
2. **GitHub** → repo *Settings → Secrets and variables → Actions*:
   - Add secret `DATABASE_URL` = the Neon string.
3. **Populate the database**: Actions tab → *Populate Live Backend* → *Run
   workflow*. (It also runs every 6h.) This migrates + ingests + computes into Neon.
4. **Render** → *New → Blueprint* → point at `infra/render.yaml` **or** create a
   single free Web Service from `backend/Dockerfile` with env:
   - `DATABASE_URL` = the Neon string
   - `RUN_MIGRATIONS` = `1`
   - `AERP_CORS_ORIGINS` = `https://saifullah5553.github.io`
   - `AERP_SECRET_KEY` = any long random string
   Copy the service URL, e.g. `https://aerp-api.onrender.com`.
5. **Point the frontend at it**: repo *Settings → Secrets and variables → Actions →
   Variables* → add variable `VITE_API_BASE` = the Render URL. Then Actions →
   *Deploy Pages* → *Run workflow*.

The Pages site now serves **live** data from your free backend. (Render's free web
service sleeps after ~15 min idle and cold-starts in ~1 min — normal for free tier.)
