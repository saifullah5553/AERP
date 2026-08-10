"""Benchmark index history, from whichever source actually carries each index.

Every market gets a benchmark. Yahoo covers four of them, and for a while that was mistaken for
the whole answer: `^KSE100` and `^DFMGI` both 404, so the quarterly history said "no index
available" for Pakistan and Dubai. Both indices exist and both are published - the symbols were
simply wrong, and one source was treated as the world.

    us         ^GSPC       Yahoo
    india      ^NSEI       Yahoo
    australia  ^AXJO       Yahoo
    gcc        ^TASI.SR    Yahoo
    dfm        DFMGI.AE    Yahoo - NOT ^DFMGI, which is what was tried and does not exist
    psx        ^KSE100     the PSX portal's own EOD series; Yahoo carries no KSE-100 at all

The closes land in the shared price pack under region "global", so everything downstream reads
an index exactly the way it reads a share price.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
# period1=0, NOT range=max. `range=max` looks like the greedy choice and silently returns
# MONTHLY bars - 168 closes for forty-two years of the S&P, which would have been stored as a
# daily series and quietly wrecked every comparison drawn from it. An explicit epoch window
# keeps interval=1d honest: the same request returns 14,271 daily closes back to 1970.
_YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
          "?period1=0&period2={until}&interval=1d")
# The exchange's own end-of-day series. dps.psx.com.pk is already the source of PSX quotes, so
# this adds a route, not a dependency.
_PSX_EOD = "https://dps.psx.com.pk/timeseries/eod/KSE100"

# Yahoo-served indices, by the symbol they are actually published under.
YAHOO_INDICES = ("^GSPC", "^NSEI", "^AXJO", "^TASI.SR", "DFMGI.AE")
PSX_INDEX = "^KSE100"


def _from_yahoo(symbol: str, client: httpx.Client) -> dict[str, float]:
    """{date: close} for an index Yahoo carries - the whole series it has, not a window."""
    until = int(datetime.now(tz=UTC).timestamp()) + 86400
    try:
        resp = client.get(_YAHOO.format(sym=symbol, until=until),
                          headers={"User-Agent": _UA}, timeout=60)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result")
        if not result:
            return {}
        block = result[0]
        stamps = block.get("timestamp") or []
        closes = ((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        offset = block.get("meta", {}).get("gmtoffset")
        if not isinstance(offset, int | float):
            offset = 0
    except Exception as exc:  # noqa: BLE001 - one index must not stop the rest
        log.warning("index %s: fetch failed (%s)", symbol, exc)
        return {}

    out: dict[str, float] = {}
    for stamp, close in zip(stamps, closes, strict=False):
        if not isinstance(stamp, int | float) or close is None:
            continue
        try:
            value = float(close)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[datetime.fromtimestamp(stamp + offset, tz=UTC).date().isoformat()] = value
    return out


def _from_psx(client: httpx.Client) -> dict[str, float]:
    """{date: close} for the KSE-100, from the exchange's own EOD endpoint.

    Rows arrive as [epoch, close, volume, ...]. Dated in Karachi, because a PSX session that
    closes at 15:30 PKT is 10:30 UTC - the same day either way, but only by luck of the hour,
    and the ledger compares these dates against trade dates that were derived locally.
    """
    try:
        resp = client.get(_PSX_EOD, headers={"User-Agent": _UA}, timeout=30)
        resp.raise_for_status()
        rows = (resp.json() or {}).get("data") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("index %s: PSX portal fetch failed (%s)", PSX_INDEX, exc)
        return {}

    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        try:
            stamp, close = float(row[0]), float(row[1])
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        out[datetime.fromtimestamp(stamp + 5 * 3600, tz=UTC).date().isoformat()] = close
    return out


def refresh_indices() -> dict[str, Any]:
    """Fetch every benchmark index and merge it into the global price pack."""
    from app.ingestion.price_pack import merge_series

    series: dict[str, dict[str, float]] = {}
    client = httpx.Client(follow_redirects=True)
    try:
        for symbol in YAHOO_INDICES:
            got = _from_yahoo(symbol, client)
            if got:
                series[symbol] = got
        psx = _from_psx(client)
        if psx:
            series[PSX_INDEX] = psx
    finally:
        client.close()

    if not series:
        log.warning("refresh-indices: nothing fetched")
        return {}
    merge_series("global", series)
    result = {sym: len(points) for sym, points in series.items()}
    log.info("refresh-indices: %s", result)
    return result
