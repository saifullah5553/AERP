"""Save this month's Zacks consensus for every US listing, to build the history nobody sells cheaply.

Zacks serves today's estimates and nothing older, so a rule built on them cannot be tested on the
past. A snapshot taken every month can test it from here on. Runs as the Scheduled Task "AERP Zacks
Monthly" on the last day of the month, on this machine, with no browser and no app.

Consensus comes from Nasdaq's public analyst API, which names Zacks as its provider, and the rank
from Zacks' open quote feed. The zacks.com estimate pages are behind bot protection: this does not
touch them, and nothing here should try to.

LOCAL ONLY. data/zacks_history is never committed: the repository is public and this is Zacks' data.
So it has no copy anywhere else, and losing this disk loses the history.

F0 growth is not in these endpoints. It comes from the Zacks screener at each rebalance.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "zacks_history"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "Chrome/120 Safari/537.36", "Accept": "application/json"}
WORKERS = 3
# Under this share answering, the sources are blocking or broken, and a thin file would pass for
# a month of history. It is kept under a name that says so.
MIN_COVERAGE = 0.5


def universe() -> list[str]:
    subprocess.run(["git", "-C", str(REPO), "-c", "gc.auto=0", "fetch", "-q", "origin", "main"],
                   check=True)
    raw = subprocess.run(["git", "-C", str(REPO), "cat-file", "-p",
                          "FETCH_HEAD:frontend/public/data/screener.json"],
                         capture_output=True, check=True).stdout
    return [str(r["symbol"]) for r in json.loads(raw)
            if r.get("region") == "us" and r.get("symbol")]


def fetch(client: httpx.Client, url: str) -> dict | None:
    for wait in (0, 3, 10):
        time.sleep(wait)
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (403, 404):
                return None
        except (httpx.HTTPError, ValueError):
            continue
    return None


def read(client: httpx.Client, symbol: str) -> dict:
    ticker = symbol.replace("-", ".")
    forecast = fetch(client, f"https://api.nasdaq.com/api/analyst/{ticker}/earnings-forecast") or {}
    peg = (fetch(client, f"https://api.nasdaq.com/api/analyst/{ticker}/peg-ratio") or {}).get("data")
    quote = fetch(client, f"https://quote-feed.zacks.com/index?t={ticker}") or {}
    data = forecast.get("data") or {}
    peg = peg or {}
    feed = quote.get(ticker) or {}
    time.sleep(0.25)
    return {
        "symbol": symbol,
        "years": (data.get("yearlyForecast") or {}).get("rows") or [],
        "pe": (peg.get("per") or {}).get("peRatioChart"),
        "growth": [g for g in ((peg.get("gr") or {}).get("peGrowthChart") or [])
                   if g.get("z") == "Growth"],
        "zacks_rank": feed.get("zacks_rank"),
        "pe_f1": feed.get("pe_f1"),
    }


def main() -> int:
    symbols = universe()
    print(f"{len(symbols)} symbols", flush=True)
    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as client:
        with ThreadPoolExecutor(WORKERS) as pool:
            rows = []
            for i, row in enumerate(pool.map(lambda s: read(client, s), symbols), 1):
                rows.append(row)
                if i % 500 == 0:
                    print(i, sum(1 for r in rows if r["years"]), flush=True)
    day = datetime.now(UTC).date().isoformat()
    answered = sum(1 for r in rows if r["years"])
    OUT.mkdir(parents=True, exist_ok=True)
    good = answered >= MIN_COVERAGE * len(rows)
    path = OUT / f"{day}{'' if good else '-thin'}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"saved": day, "rows": rows}, fh)
    print(f"{path.name}: {answered} of {len(rows)} with estimates", flush=True)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
