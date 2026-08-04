"""Our own daily OHLC history, accumulated bar by bar.

The division of labour across the platform: fundamentals come from stockanalysis, prices and
daily OHLC come from Yahoo (and the PSX feed for Pakistan). Both are other people's servers.
This keeps a local copy of every bar we have ever seen, so the price history stops being
something we re-borrow on every run and starts being something we own.

That matters most where the upstream window is short or the source is unreliable. Yahoo serves
a rolling range - ask for 5 years today and you get the last 5 years, so a bar from six years
ago is simply gone unless we wrote it down. PSX's own portal has been unreachable for stretches
of this project. Appending forever is the only way to end up with history nobody can take back.

Append-only and idempotent: re-running re-writes nothing, and a bar already stored is never
replaced by a later fetch. Restatements are rare; silently overwriting a stored bar with a
different value would corrupt a backtest in a way nothing downstream could detect.

    data/ohlc/<region>/<SYMBOL>.csv     date,open,high,low,close,volume   (ascending)
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.ingestion.symbols import YAHOO_SUFFIX, yahoo

log = get_logger(__name__)

STORE = Path(__file__).resolve().parents[3] / "data" / "ohlc"
HEADER = ["date", "open", "high", "low", "close", "volume"]

# Windows refuses files named after a device, and the snapshot is authored on Windows.
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
             *(f"LPT{i}" for i in range(10))}


def _path(region: str, symbol: str, store: Path | None = None) -> Path | None:
    # '/' and ':' cannot appear in a filename; tickers rarely contain them but forex and some
    # listings do, so map rather than crash the batch.
    safe = symbol.upper().replace("/", "_").replace(":", "_")
    if safe.split(".", 1)[0] in _RESERVED:
        return None
    return (store or STORE) / region / f"{safe}.csv"


def load_bars(region: str, symbol: str, store: Path | None = None) -> dict[str, list]:
    """{date: row} for everything already stored."""
    path = _path(region, symbol, store)
    if path is None or not path.exists():
        return {}
    out: dict[str, list] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                d = (row.get("date") or "").strip()
                if d:
                    out[d] = [row.get(k) for k in HEADER]
    except OSError:
        return {}
    return out


def save_bars(region: str, symbol: str, bars: list[dict],
              store: Path | None = None) -> int:
    """Merge `bars` into the stored history. Returns how many were genuinely new.

    Existing dates are kept as first written - see the note on restatements above.
    """
    path = _path(region, symbol, store)
    if path is None:
        return 0
    have = load_bars(region, symbol, store)
    added = 0
    for b in bars:
        d = str(b.get("date") or "")[:10]
        if not d or d in have or b.get("close") is None:
            continue
        have[d] = [d, b.get("open"), b.get("high"), b.get("low"), b.get("close"),
                   b.get("volume")]
        added += 1
    if not added:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for d in sorted(have):
            w.writerow(have[d])
    tmp.replace(path)  # atomic: a killed run never leaves a half-written history
    return added


def bars_from_chart(res: dict) -> list[dict]:
    """Yahoo chart-v8 payload -> daily bars."""
    ts = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    opens, highs = quote.get("open") or [], quote.get("high") or []
    lows, vols = quote.get("low") or [], quote.get("volume") or []

    def at(seq, i):
        return seq[i] if i < len(seq) else None

    out: list[dict] = []
    for i, close in enumerate(closes):
        if close is None or i >= len(ts) or ts[i] is None:
            continue
        out.append({
            "date": datetime.fromtimestamp(ts[i], UTC).date().isoformat(),
            "open": at(opens, i), "high": at(highs, i), "low": at(lows, i),
            "close": close, "volume": at(vols, i),
        })
    return out


def refresh(region: str, symbols: list[str], range_: str = "1y",
            store: Path | None = None, pause: float = 0.05,
            workers: int = 8) -> dict[str, int]:
    """Fetch each symbol's daily history from Yahoo and append what is new.

    Concurrent because these are thousands of small independent GETs and serial fetching put a
    full backfill in the hours. Each symbol owns its own file, so only the counters are shared.
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    url = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    lock = threading.Lock()
    seen = added = failed = 0

    def one(sym: str, client: httpx.Client) -> None:
        nonlocal seen, added, failed
        got, bad = 0, False
        try:
            r = client.get(url.format(sym=yahoo(region, sym)),
                           params={"range": range_, "interval": "1d"})
            res = ((r.json().get("chart") or {}).get("result") or [None])[0]
            if r.status_code != 200 or not res:
                bad = True
            else:
                got = save_bars(region, sym, bars_from_chart(res), store)
        except Exception:  # noqa: BLE001 - one bad symbol must not stop the sweep
            bad = True
        with lock:
            seen += 1
            added += got
            failed += bad
            if seen % 500 == 0:
                log.info("ohlc %s: %d/%d (%d bars added, %d failed)",
                         region, seen, len(symbols), added, failed)
        time.sleep(pause)

    with (
        httpx.Client(timeout=20, headers={"User-Agent": ua}) as client,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        list(pool.map(lambda s: one(s, client), symbols))

    result = {"symbols": seen, "bars_added": added, "failed": failed}
    log.info("ohlc refresh %s: %s", region, result)
    return result


def coverage(store: Path | None = None) -> dict[str, dict]:
    """How much history we actually own, per market."""
    root = store or STORE
    out: dict[str, dict] = {}
    for region in YAHOO_SUFFIX:
        d = root / region
        if not d.exists():
            continue
        files = list(d.glob("*.csv"))
        bars = 0
        for f in files:
            # Counted with the handle closed each time: coverage() walks ~12k files, and
            # leaking a descriptor per file exhausts the limit long before it finishes.
            with open(f, encoding="utf-8") as fh:
                bars += max(0, sum(1 for _ in fh) - 1)
        out[region] = {"symbols": len(files), "bars": bars}
    return out
