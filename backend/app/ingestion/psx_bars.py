"""Daily PSX bars, from the exchange's own EOD endpoint.

WHY THIS EXISTS. PSX had no working path to advance its daily bars, and the effect was
invisible: `refresh_technicals` takes `skip_regions=("psx",)` so PSX never enters the Yahoo
pass that folds closes into the price pack, and the local OHLC CSVs stopped on 3 August. The
scheduled portal market-watch keeps PSX PRICES current, so the screener looked perfectly
healthy while every PSX technical score, divergence and signal date was computed on a chart
that had not moved for nineteen days. A stale chart and a chart that has not moved look
identical from the outside.

THE ENDPOINT WAS NEVER DEAD - WE WERE BEING RATE LIMITED. It was recorded as serving
/timeseries/eod/KSE100 and "disconnecting without a response" for LUCK, ATLH and every other
company, and the signal-date backfill was moved off it on that basis. Measured properly: a
cold client fetches LUCK, MCB, OGDC and HUBC without complaint, six concurrent workers get
through about a hundred symbols, and after that EVERY symbol disconnects - including the ones
that had just succeeded. That is an IP cooldown, not a missing endpoint, and it produces
exactly the symptom that was mistaken for one.

SINCE ~24 SEP 2026 THE EXCHANGE REFUSES /market-watch AND /timeseries/* TO DIRECT REQUESTS, so
the paragraph above is history and `fetch_symbol` below no longer returns anything. The daily
path is now `refresh_psx_daily`:

  * THE EXCHANGE'S PUBLIC /screener - the session's price for every listed company, one request.
  * YAHOO'S DAILY CLOSES (.KA) - what the exchange page lacks: volume and history. They are
    only accepted when they RECONCILE. Measured across 412 names, Yahoo's last close matched
    the exchange's implied previous close to the rupee for almost all of them (LUCK 415.14,
    UBL 422.00, OGDC 310.47), but GIL read 125.85 against 1,000 and SGABL 3.38 against 126.
    A series that disagrees is dropped and the symbol keeps the exchange's price alone.

Everything downstream still reads the pack; this only advances the store it reads from.

Each row is ``[unix_ts, adjusted_close, volume, raw_close]``; the adjusted close is kept so
indicators stay continuous across splits, matching `psx_market.parse_eod`.
"""

from __future__ import annotations

import datetime
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

EOD_URL = "https://dps.psx.com.pk/timeseries/eod/{symbol}"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Referer": "https://dps.psx.com.pk/",
    "Accept": "application/json, text/plain, */*",
}


def fetch_symbol(symbol: str, client: httpx.Client) -> dict[str, float]:
    """{date: close} for one PSX company, or {} when the portal will not serve it."""
    try:
        resp = client.get(EOD_URL.format(symbol=symbol), headers=_HEADERS, timeout=25)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001 - one bad symbol must not stop the batch
        return {}
    rows = (payload or {}).get("data") or []
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        try:
            ts = int(row[0])
            close = float(row[1])
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        day = datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).date().isoformat()
        out[day] = close
    return out


# Measured against the live portal: six concurrent workers are cut off after ~100 symbols.
# One at a time with a pause holds. The cap keeps a single run inside a sensible budget and,
# because the pack merges, the remainder simply lands on the next run.
THROTTLE_SECONDS = 1.2
MAX_PER_RUN = 200
CONSECUTIVE_FAILURES_BEFORE_STOP = 12


def refresh_psx_bars(symbols: list[str], limit: int | None = None) -> dict[str, int]:
    """Fetch PSX symbols, paced, and merge the closes into the price pack."""
    from app.ingestion.price_pack import merge_series

    targets = symbols[: (limit or MAX_PER_RUN)]
    series: dict[str, dict[str, float]] = {}
    empty = 0
    streak = 0
    with httpx.Client(follow_redirects=True) as client:
        for sym in targets:
            points = fetch_symbol(sym, client)
            if points:
                series[sym] = points
                streak = 0
            else:
                empty += 1
                streak += 1
                # Stop on a run of failures rather than grinding through the remaining
                # hundreds. Once the portal starts refusing it refuses everything, so
                # continuing only deepens the cooldown for the next run.
                if streak >= CONSECUTIVE_FAILURES_BEFORE_STOP:
                    log.warning("psx-bars: %d consecutive empties - portal is refusing, "
                                "stopping after %d symbols", streak, len(series) + empty)
                    break
            time.sleep(THROTTLE_SECONDS)

    if not series:
        # Loud, because this is the failure the module exists to make visible. Returning
        # quietly would put PSX straight back where it was: silently frozen.
        log.warning("psx-bars: the portal served NOTHING for any of %d symbols", len(symbols))
        return {"symbols": 0, "empty": empty, "points": 0}

    result = merge_series("psx", series)
    newest = max((max(p) for p in series.values() if p), default=None)
    log.info("psx-bars: %d symbols fetched (%d empty), newest bar %s, pack now %s",
             len(series), empty, newest, result)
    return {"symbols": len(series), "empty": empty, "newest": newest, **result}


# Yahoo's last close must sit this close to the exchange's implied previous close, and to what
# we already hold for that day. Wider than rounding, far narrower than the bad listings.
RECONCILE_TOLERANCE = 0.01
HISTORY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.KA?range=3mo&interval=1d"
_PKT = datetime.timedelta(hours=5)


def fetch_yahoo_history(symbol: str, client: httpx.Client) -> dict[str, tuple[float, float | None]]:
    """{date: (close, volume)} for one PSX company, dated in Karachi, or {} if Yahoo has none."""
    try:
        resp = client.get(HISTORY_URL.format(symbol=symbol),
                          headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=20)
        resp.raise_for_status()
        block = resp.json()["chart"]["result"][0]
        quote = block["indicators"]["quote"][0]
        stamps, closes, volumes = block["timestamp"], quote["close"], quote["volume"]
    except Exception:  # noqa: BLE001 - one bad symbol must not stop the batch
        return {}
    out: dict[str, tuple[float, float | None]] = {}
    for stamp, close, volume in zip(stamps, closes, volumes, strict=False):
        if close and close > 0:
            day = (datetime.datetime.fromtimestamp(stamp, tz=datetime.UTC) + _PKT).date()
            out[day.isoformat()] = (float(close), float(volume) if volume is not None else None)
    return out


def reconciles(history: dict[str, tuple[float, float | None]], prev_close: float | None,
               session: str, stored: dict[str, float] | None = None) -> bool:
    """Does this series agree with the exchange, and with what we already hold?"""
    settled = sorted(day for day in history if day < session)
    if not settled or not prev_close:
        return False
    last = history[settled[-1]][0]
    if abs(last / prev_close - 1) > RECONCILE_TOLERANCE:
        return False
    # A split re-bases the whole series, so it can agree today and disagree with our history.
    # The MEDIAN across shared days, because stored closes from 30 Aug to 24 Sep 2026 sit one
    # session late (see repair note in refresh_psx_daily): any single day can differ by a
    # day's move, while a re-based series differs on all of them.
    shared = [day for day in settled if stored and day in stored][-20:]
    if shared:
        ratios = sorted(history[day][0] / stored[day] for day in shared)
        return abs(ratios[len(ratios) // 2] - 1) <= RECONCILE_TOLERANCE
    return True


def refresh_psx_daily(workers: int = 6) -> dict[str, object]:
    """Advance the PSX pack: the exchange's price for the session, Yahoo for history and volume."""
    from app.ingestion.price_pack import load_packed, merge_series
    from app.ingestion.psx_market import fetch_public_market

    try:
        market = fetch_public_market()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed into a silent zero
        log.error("psx-bars: public pages failed (%s) - PSX bars NOT advanced", exc)
        return {"symbols": 0, "error": type(exc).__name__}
    if not market.quotes or market.as_of is None:
        log.error("psx-bars: %d quotes, session %s - PSX bars NOT advanced",
                  len(market.quotes), market.as_of)
        return {"symbols": 0, "quotes": len(market.quotes)}

    session = market.as_of.isoformat()
    stored = load_packed("psx")
    wanted = sorted(set(stored) & set(market.quotes))
    with httpx.Client(follow_redirects=True) as client, ThreadPoolExecutor(workers) as pool:
        histories = dict(zip(wanted, pool.map(lambda s: fetch_yahoo_history(s, client), wanted),
                             strict=True))

    series = {s: {session: q.price} for s, q in market.quotes.items() if s in stored}
    volumes: dict[str, dict[str, float]] = {}
    accepted, rejected, absent = 0, [], 0
    for symbol, history in histories.items():
        if not history:
            absent += 1
        elif reconciles(history, market.quotes[symbol].prev_close, session, stored.get(symbol)):
            accepted += 1
            # Yahoo's bar for the live session is partial; the exchange's price stands for it.
            # Overwriting the whole window is deliberate: the old market-watch path stamped
            # each close with the UTC date at run time, and CI runs after midnight, so closes
            # from 30 Aug to 24 Sep 2026 were filed one session late.
            for day, (close, volume) in history.items():
                if day < session:
                    series[symbol][day] = close
                    if volume is not None:
                        volumes.setdefault(symbol, {})[day] = volume
        else:
            rejected.append(symbol)

    result = merge_series("psx", series, volumes=volumes)
    log.info("psx-bars: session %s, %d symbols; Yahoo history accepted %d, rejected %d %s, "
             "absent %d; pack now %s", session, len(series), accepted, len(rejected),
             rejected[:12], absent, result)
    return {"symbols": len(series), "session": session, "history": accepted,
            "rejected": len(rejected), "absent": absent, **result}
