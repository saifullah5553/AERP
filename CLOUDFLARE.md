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

## 1 · Create the account and project

1. Sign up at <https://dash.cloudflare.com/sign-up>. No card is required for what this uses.
2. **Workers & Pages → Create → Pages → Connect to Git**, pick `saifullah5553/AERP`.
3. When it asks for build settings, **skip / cancel the git integration** and finish creating
   an empty project named exactly **`aerp`**.

That last step is deliberate. Cloudflare's own git build would need to check out a 5 GB
repository on every deploy. The workflow here builds on a GitHub runner, where the checkout is
already warm, and uploads only `dist`.

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
CLOUDFLARE_ACCOUNT_ID   the account id from the sidebar
```

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

**`screener.json` is 22.9 MB against a 25 MB cap**, and it grows with the universe. The deploy
workflow checks this before uploading and fails with the offending filename, so it will stop
being a surprise — but the fix is to split the screener per market, which also fixes the far
more pressing problem that 22.9 MB is a brutal first load on a phone.

**11,030 files is comfortable now** and would only bind if the company universe roughly
doubled.

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

## Using the live-price proxy

The Worker is deployed and callable, but the frontend does **not** call it yet — that is a
separate change to the screener, kept apart so this deploy can be verified on its own.

```
GET /quote?symbols=AAPL,MSFT,LUCK.KA   → { quotes: { AAPL: { price, change, changePct, ... } } }
GET /psx                               → the whole PSX market in one upstream request
GET /health
```

Check it with:

```bash
curl "https://aerp-price-proxy.<your-subdomain>.workers.dev/quote?symbols=AAPL,LUCK.KA"
```
