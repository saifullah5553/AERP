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

TWO PATHS, and the cheap one is the default:

  * MARKET WATCH - ONE request returns today's close for the whole market. No per-symbol
    traffic, so no cooldown to trip, and the pipeline already calls this endpoint every
    thirty minutes for prices. Appending those closes to the pack is all that was ever
    needed to keep PSX bars current; it simply was never wired up. This is what runs daily.
  * PER-SYMBOL EOD - paced and capped, and only for BACKFILLING history a symbol is missing.
    One request at a time with a delay, a ceiling per run, and the pack merges so partial
    runs accumulate rather than compete.

Everything downstream still reads the pack; this only advances the store it reads from.

Each row is ``[unix_ts, adjusted_close, volume, raw_close]``; the adjusted close is kept so
indicators stay continuous across splits, matching `psx_market.parse_eod`.
"""

from __future__ import annotations

import datetime
import time

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


def refresh_from_market_watch() -> dict[str, int]:
    """Append today's close for the WHOLE market from a single request.

    The cheap path, and the one that keeps PSX bars current day to day. `parse_market_watch`
    already backs the scheduled price ingest, so this adds no new traffic and cannot trip
    the per-symbol cooldown - it just stops throwing the closes away once the prices have been
    read out of them.
    """
    from app.ingestion.price_pack import merge_series

    # PSXPortalClient, not PsxClient. The wrong name made this raise ImportError on EVERY run
    # - and because the import sits inside the function, above the try, it escaped the except
    # below and was then swallowed by the workflow's `|| true`. PSX bars stopped advancing on
    # 2026-08-21 and nothing went red for nine days: prices stayed current from the scheduled
    # ingest, so the screener looked healthy while every PSX technical was computed on a chart
    # that had stopped. The freshness checker is what caught it.
    from app.ingestion.psx_market import PSXPortalClient, parse_market_watch

    try:
        rows = parse_market_watch(PSXPortalClient().market_watch())
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed into a silent zero
        log.warning("psx-bars: market-watch fetch failed (%s)", exc)
        return {"symbols": 0, "source": "market-watch", "error": type(exc).__name__}

    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    series = {r.symbol: {today: float(r.close)}
              for r in rows if r.symbol and r.close and r.close > 0}
    # VOLUME TOO. market-watch carries it and the pack now stores it, which matters more for
    # PSX than anywhere else: the Elder Force Index is close times volume, so without it the
    # EFI half of the divergence page quietly degrades to RSI-only, and the volume component
    # of the technical score has nothing to score.
    volumes = {r.symbol: {today: float(r.volume)}
               for r in rows if r.symbol and r.volume is not None and r.volume >= 0}
    if not series:
        log.warning("psx-bars: market-watch returned %d rows and no usable closes", len(rows))
        return {"symbols": 0, "source": "market-watch"}

    result = merge_series("psx", series, volumes=volumes)
    log.info("psx-bars(market-watch): %d symbols closed %s (%d with volume), pack now %s",
             len(series), today, len(volumes), result)
    return {"symbols": len(series), "volumes": len(volumes), "day": today,
            "source": "market-watch", **result}
