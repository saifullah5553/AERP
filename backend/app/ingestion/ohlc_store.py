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

import contextlib
import csv
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.ingestion.split_adjust import adjust as split_adjust
from app.ingestion.split_adjust import parse_splits
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


# A stored price and a freshly fetched one for the SAME day should match. When they differ by
# the same factor across the overlap, the vendor has re-based the series - a split - and the
# history we hold is on the old basis.
_REBASE_TOLERANCE = 0.02      # 2%: below this it is rounding, not a split
_REBASE_MIN_OVERLAP = 3       # one disagreeing day is a bad print, not a corporate action


def _rebase_factor(have: dict[str, list], incoming: dict[str, float]) -> float | None:
    """How much the stored history is out by, or None when it agrees with the vendor.

    Measured on the OLDEST overlapping days, because that is the side of any split that is
    still on the old basis. A clean 1.0 means nothing happened.
    """
    overlap = sorted(set(have) & set(incoming))
    if len(overlap) < _REBASE_MIN_OVERLAP:
        return None
    ratios = []
    for d in overlap[:8]:
        try:
            old, new = float(have[d][4]), float(incoming[d])
        except (TypeError, ValueError, IndexError):
            continue
        if old > 0 and new > 0:
            ratios.append(old / new)
    if len(ratios) < _REBASE_MIN_OVERLAP:
        return None
    ratios.sort()
    factor = ratios[len(ratios) // 2]
    if abs(factor - 1.0) <= _REBASE_TOLERANCE:
        return None
    # Every one of them has to agree. A split moves the whole series by one number; a handful
    # of odd prints do not, and rescaling five years of history off those would be worse than
    # the cliff it is trying to remove.
    if any(abs(r / factor - 1.0) > _REBASE_TOLERANCE for r in ratios):
        return None
    return factor


def save_bars(region: str, symbol: str, bars: list[dict],
              store: Path | None = None, events: dict | None = None) -> int:
    """Merge `bars` into the stored history. Returns how many were genuinely new.

    A freshly fetched day WINS over a stored one, and history is re-based when the vendor has
    split-adjusted it. The store used to keep every date as first written, which is right for a
    restatement and wrong for a split: Yahoo re-issues the whole series divided by the split
    factor, so the old rows stayed raw while new rows arrived adjusted and the series gained a
    permanent cliff. DLL showed a 10x drop overnight and the ledger read it as an 88.9% loss.
    """
    path = _path(region, symbol, store)
    if path is None:
        return 0
    have = load_bars(region, symbol, store)

    incoming: dict[str, float] = {}
    for b in bars:
        d = str(b.get("date") or "")[:10]
        if d and b.get("close") is not None:
            try:
                incoming[d] = float(b["close"])
            except (TypeError, ValueError):
                continue

    factor = _rebase_factor(have, incoming) if have and incoming else None
    if factor:
        # Bring the whole stored history onto the vendor's current basis. Prices divide;
        # volume multiplies, since a 10:1 split leaves ten times as many shares changing hands.
        log.info("ohlc %s/%s: re-basing history by %.4f (split-adjusted upstream)",
                 region, symbol, factor)
        for row in have.values():
            # Prices divide by the factor; volume multiplies, since a 5:1 split leaves five
            # times as many shares changing hands for the same money.
            for i, scale in ((1, factor), (2, factor), (3, factor), (4, factor),
                             (5, 1.0 / factor)):
                with contextlib.suppress(TypeError, ValueError):
                    if row[i] not in (None, ""):
                        row[i] = float(row[i]) / scale

    added = 0
    for b in bars:
        d = str(b.get("date") or "")[:10]
        if not d or b.get("close") is None:
            continue
        if d not in have:
            added += 1
        # Overwrite, not skip: the vendor's current view of a day is the correct one, and
        # keeping our first copy is what let the two bases coexist in one file.
        have[d] = [d, b.get("open"), b.get("high"), b.get("low"), b.get("close"),
                   b.get("volume")]
    # Restate the whole series for any split the vendor reported. Yahoo does not do this for
    # PSX - its adjclose is identical to its close - so the raw history keeps the 5x cliff, and
    # a holding bought before the split reads as an 80% loss it never took.
    restated = 0
    if events:
        splits = parse_splits(events)
        if splits:
            have, restated = split_adjust(have, splits)

    if not added and not factor and not restated:
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
                           params={"range": range_, "interval": "1d",
                                   "events": "split"})
            res = ((r.json().get("chart") or {}).get("result") or [None])[0]
            if r.status_code != 200 or not res:
                bad = True
            else:
                got = save_bars(region, sym, bars_from_chart(res), store,
                                events=res.get("events"))
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
