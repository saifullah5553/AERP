# Cloudflare deploy — website + PWA, free tier

Everything in the repo is built and verified. What is left needs your Cloudflare account, so
it cannot be automated from here: creating the account, minting an API token, and pasting two
secrets into GitHub. Fifteen minutes, once.

---

## What was built

| piece | where | what it does |
|---|---|---|
| Pages site | `frontend/dist` | the whole terminal, served from Cloudflare's edge |
| PWA | `frontend/public/manifest.webmanifest`, `sw.js`, `icons/` | installable, works offline |
| Price proxy | `workers/price-proxy/` | live quotes in the browser, which CORS otherwise forbids |
| Deploy | `.github/workflows/deploy-cloudflare.yml` | pushes both on every `main` build |

The GitHub Pages deploy is untouched and still runs. Both sites stay up until Cloudflare has
proven itself — switching off the working one first is how you find out it did not.

---

## 1 · Nothing to click

The workflow creates the Pages project itself (`wrangler pages project create aerp`). The
dashboard is not involved, which matters because it keeps being reorganised - "Workers & Pages"
moved under **Compute** in the 2026 redesign, and an instruction naming a menu item ages badly.

The project is deliberately NOT connected to Git. Cloudflare's own Git build would check out a
5 GB repository on every deploy; the workflow builds on a GitHub runner and uploads only
`dist`.

## 2 · Mint an API token

**My Profile → API Tokens → Create Token → Create Custom Token**

| permission | scope |
|---|---|
| Account · Cloudflare Pages · **Edit** | your account |
| Account · Workers Scripts · **Edit** | your account |

Copy the token — it is shown once. Your **Account ID** is in the right-hand sidebar of the
dashboard home page.

## 3 · Add two GitHub secrets

**Repo → Settings → Secrets and variables → Actions → New repository secret**

```
CLOUDFLARE_API_TOKEN    the token from step 2
CLOUDFLARE_ACCOUNT_ID   c4dd7cad6f3c53dc853e7a6af8ead80c
```

The account id is the hex string in your dashboard URL, so it needs no hunting.

Until both exist the deploy workflow **skips** rather than fails. An unconfigured deploy is not
a broken build, and a permanently red run is exactly how a real failure gets ignored.

## 4 · Deploy

Push to `main`, or run **Deploy to Cloudflare** manually from the Actions tab.

You get:

- `https://aerp.pages.dev` — the site
- `https://aerp-price-proxy.<your-subdomain>.workers.dev` — the proxy

## 5 · Install the app

Open the site on a phone.

- **Android / Chrome** — "Add to Home screen" appears on its own, or use the ⋮ menu.
- **iOS / Safari** — Share → "Add to Home Screen". (Safari does not offer an install prompt;
  that is an Apple restriction, not a gap here.)

It opens without browser chrome, keeps the last snapshot offline, and reads the dark theme
into the status bar.

---

## Free-tier limits, and where this actually sits

| limit | free allowance | us |
|---|---|---|
| Pages bandwidth | unlimited | fine |
| Pages builds | 500/month | we build on GitHub, so 0 |
| Files per deployment | 20,000 | **11,030** |
| Single file | 25 MB | **`screener.json` at 22.9 MB** |
| Worker requests | 100,000/day | a heavy session is a few hundred |

Two of those deserve attention rather than a tick.

**`screener.json` is 22.9 MB against a 25 MB cap.** That is the STORED size, which is what the
cap measures. The deploy checks it before uploading and fails with the filename, so it stops
being a surprise; ~9% headroom, and the universe just shrank by 921 exclusions, so it is not
urgent.

**Over the wire it is 3.7 MB, not 22.9.** Cloudflare gzips text automatically and this file
compresses to 16%. An earlier note here called it a brutal mobile load on the raw number — that
was wrong. 3.7 MB is heavy-ish on a phone but not remotely the same problem.

Splitting per market is still worth doing eventually, and the measured prize is real: a PSX-only
user would pull 0.2 MB instead of 3.7 MB.

    us 1.9 MB gzip | india 0.9 | australia 0.4 | psx 0.2 | gcc 0.1 | dfm 0.02

**11,030 files is comfortable** and would only bind if the universe roughly doubled.

## The bigger constraint, which Cloudflare does not solve on its own

The repository is **5.04 GB** and GitHub's soft limit is 5 GB. 1,040 of the last 1,244 commits
touched the snapshot: a 459 MB directory rewritten up to 48 times a day, with every version
kept forever. Moving the *hosting* to Cloudflare does not change that, because the data still
arrives through git.

The fix is R2 (10 GB free, no egress charges): the refresh writes the snapshot to a bucket
instead of committing it, and the repo goes back to holding code. Worth doing next, and worth
deciding one thing first — today you can `git show` last Tuesday's screener, and that has been
genuinely useful this week for tracing what changed. R2 has versioning but it is not free-tier
generous, so that history is a real thing to give up on purpose rather than by accident.

## Live prices — one more variable to set

The frontend now uses the proxy, but only when it is told where to find it.

After the first deploy, note the Worker URL and add it as a repository **variable** (Settings →
Secrets and variables → Actions → **Variables**, not Secrets — it is a public URL):

```
VITE_PRICE_PROXY = https://aerp-price-proxy.<your-subdomain>.workers.dev
```

Then re-run the deploy. Unset, the site simply uses snapshot prices exactly as it does today —
it degrades, it does not break.

With it set, the screener polls the proxy every 20 seconds for **only the rows currently
rendered**, and the LIVE indicator lights up. Background tabs stop polling. A failed poll drops
the indicator rather than leaving the page claiming to be live.

Verified end to end before shipping, by serving the real Worker over HTTP and consuming it with
the exact code path the client uses:

```
AAPL     price=309.90  change_pct=-0.14
MSFT     price=491.71  change_pct=+0.90
LUCK.KA  price=440.03  change_pct=-0.09
```

```
GET /quote?symbols=AAPL,MSFT,LUCK.KA   → { quotes: { AAPL: { price, change, changePct, ... } } }
GET /psx                               → the whole PSX market in one upstream request
GET /health
```

Check it with:

```bash
curl "https://aerp-price-proxy.<your-subdomain>.workers.dev/quote?symbols=AAPL,LUCK.KA"
```

---

## Why GitHub is in the loop, and what happens when it fails

**The pipeline has to run somewhere.** Scoring, valuation, technicals and the scrapers are
Python. Cloudflare cannot run them, and its own Git build would check out a 5 GB repository on
every deploy. GitHub Actions is free and unlimited on public repos, so that is where the data
is made.

**But the deploy does not have to be coupled to it, and originally it was.** Bundling the
snapshot into the deployment ties together two things that fail for different reasons on
different schedules: the app shell changes when code changes (rarely), the data changes every
thirty minutes. Coupled, a failed deploy freezes the DATA, because publishing new data means
redeploying the whole site.

Set `VITE_DATA_BASE` and they come apart:

```
VITE_DATA_BASE = https://saifullah5553.github.io/AERP/data
```

    bundled       11,051 files   440 MB
    shell only        12 files     5.4 MB

GitHub Pages serves the snapshot with `access-control-allow-origin: *`, so this works
cross-origin today with no new infrastructure. What it buys is failure isolation:

| what breaks | before | after |
|---|---|---|
| Cloudflare deploy fails | data frozen at last deploy | last good shell keeps serving CURRENT data |
| Pipeline fails | site fine, data silently stale | same, and `verify-freshness` turns the run red |
| GitHub Pages down | — | site loads, data does not (cached copy shown offline) |
| Cloudflare down | site down | GitHub Pages copy still up |

Both deploys run, so there are always two live copies of the site.

**The one remaining single point is the pipeline itself** - if GitHub Actions stops entirely,
data stops updating everywhere. That is not fixable by hosting; it is fixable by noticing, which
is what `verify-freshness` is for. It checks 24 things and exits non-zero, so a stall becomes a
red run the same day rather than a discovery weeks later.
