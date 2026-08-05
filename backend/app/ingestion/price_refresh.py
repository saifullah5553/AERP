"""Keyless price refresh for the static snapshot via Yahoo's chart v8 endpoint.

Unlike ``yfinance``'s quote/download endpoints (which 429 from datacenter/CI IPs), the
lightweight ``/v8/finance/chart/{symbol}`` endpoint IS reachable from GitHub runners and
returns the current (≈15-min delayed) quote for US/India/GCC/Australia/forex/etc.

This patches ONLY the price fields (price/change/change_pct/volume) in the already-exported
screener.json + company/*.json — it never touches scores, fundamentals, or regime, so a
price refresh can never degrade the rest of the snapshot. PSX is skipped (not on Yahoo; its
prices come from the PSX portal in the main pipeline).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.ingestion.ohlc_store import load_bars

log = get_logger(__name__)

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"


def parse_chart_meta(meta: dict[str, Any]) -> dict[str, Any] | None:
    """Latest quote from a chart-v8 ``meta`` block, or None if there's no usable price."""
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("chartPreviousClose")
    if prev is None:
        prev = meta.get("previousClose")
    out: dict[str, Any] = {
        "price": price,
        "prev_close": prev,
        "day_open": meta.get("regularMarketOpen"),
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
    }
    if prev not in (None, 0):
        out["change"] = round(price - prev, 6)
        out["change_pct"] = round((price - prev) / prev * 100.0, 6)
    else:
        out["change"] = None
        out["change_pct"] = None
    return out


def fetch_quote(sym: str, client: httpx.Client) -> dict[str, Any] | None:
    try:
        resp = client.get(_CHART.format(sym=sym), headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"]
        if not result:
            return None
        return parse_chart_meta(result[0]["meta"])
    except Exception:  # noqa: BLE001 - one bad/delisted symbol shouldn't stop the batch
        return None


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _eps_ttm(detail: dict) -> float | None:
    """Trailing-twelve-month EPS from a company file's income statements.

    Prefers the sum of the last 4 *quarterly* EPS (a true TTM); falls back to the most
    recent *annual* EPS (itself a full trailing year) when no quarterly data exists — the
    case for every PSX name, whose only filings here are annual.
    """
    inc = ((detail.get("statements") or {}).get("income")) or []
    if not isinstance(inc, list):
        return None

    def _fd(x: dict) -> str:
        return x.get("fiscal_date") or x.get("period_end") or ""

    q = sorted(
        [x for x in inc if x.get("period") == "quarterly" and x.get("eps") is not None],
        key=_fd, reverse=True,
    )
    if len(q) >= 4:
        return round(sum(float(x["eps"]) for x in q[:4]), 4)
    a = sorted(
        [x for x in inc if x.get("period") == "annual" and x.get("eps") is not None],
        key=_fd, reverse=True,
    )
    if a:
        return round(float(a[0]["eps"]), 4)
    return None


def _pe_ttm(price: Any, eps_ttm: float | None) -> float | None:
    """P/E (TTM). None for missing/zero/negative EPS (a loss has no meaningful P/E)."""
    if price is None or eps_ttm is None or eps_ttm <= 0:
        return None
    return round(float(price) / eps_ttm, 2)


def _add_psx_quotes(rows: list[dict], quotes: dict[str, dict]) -> None:
    """Populate `quotes` (keyed by provider_symbol) for PSX names from the official
    dps.psx.com.pk/market-watch table (live close/change/volume for the whole market)."""
    psx_map = {
        r.get("symbol"): r.get("provider_symbol")
        for r in rows
        if r.get("region") == "psx" and r.get("symbol") and r.get("provider_symbol")
    }
    if not psx_map:
        return
    try:
        from app.ingestion.psx_market import parse_market_watch, parse_symbols

        resp = httpx.get(
            "https://dps.psx.com.pk/market-watch", headers={"User-Agent": _UA}, timeout=25
        )
        resp.raise_for_status()
        marketrows = parse_market_watch(resp.text)
    except Exception as exc:  # noqa: BLE001 - network optional
        log.warning("PSX market-watch fetch failed: %s", exc)
        return

    # Sector per symbol from /symbols (title-cased), so PSX names get proper sectors.
    sectors: dict[str, str] = {}
    try:
        sresp = httpx.get(
            "https://dps.psx.com.pk/symbols", headers={"User-Agent": _UA}, timeout=25
        )
        sresp.raise_for_status()
        for s, meta in parse_symbols(sresp.text).items():
            if meta.sector:
                sectors[s] = meta.sector.title()
    except Exception as exc:  # noqa: BLE001 - network optional
        log.warning("PSX /symbols fetch failed: %s", exc)
    for mr in marketrows:
        ps = psx_map.get(mr.symbol)
        if not ps:
            continue
        price = mr.close if mr.close is not None else mr.ldcp
        if price is None:
            continue
        prev = mr.ldcp
        change = mr.change
        change_pct = mr.change_pct
        if change is None and prev not in (None, 0):
            change = round(price - prev, 4)
        if change_pct is None and prev not in (None, 0):
            change_pct = round((price - prev) / prev * 100.0, 4)
        quotes[ps] = {
            "price": price, "prev_close": prev, "change": change, "change_pct": change_pct,
            "day_open": mr.open, "day_high": mr.high, "day_low": mr.low, "volume": mr.volume,
            "sector": sectors.get(mr.symbol),
        }
    log.info("PSX market-watch: %d symbols patched", sum(1 for k in quotes if k.endswith(".KA")))


def refresh_prices(
    data_dir: str | Path,
    skip_regions: tuple[str, ...] = ("psx",),
    workers: int = 8,
    limit: int | None = None,
) -> dict[str, int]:
    """Patch price fields in screener.json + company/*.json for non-skipped regions."""
    out = Path(data_dir)
    screener_path = out / "screener.json"
    rows: list[dict] = _load(screener_path)

    targets = [
        r for r in rows
        if r.get("region") not in skip_regions and r.get("provider_symbol")
    ]
    if limit is not None:
        targets = targets[:limit]

    quotes: dict[str, dict] = {}
    syms = [r["provider_symbol"] for r in targets]
    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for sym, q in zip(syms, pool.map(lambda s: fetch_quote(s, client), syms), strict=False):
                if q is not None:
                    quotes[sym] = q
    finally:
        client.close()

    # PSX prices from the official market-watch (Yahoo has no PSX). Patched directly here so
    # PSX stays robust even if the DB-based ingest hiccups. One fetch for the whole market.
    _add_psx_quotes(rows, quotes)

    updated = 0
    for r in rows:
        q = quotes.get(r.get("provider_symbol"))
        if not q:
            continue
        r["price"] = q["price"]
        r["change"] = q["change"]
        r["change_pct"] = q["change_pct"]
        if q.get("volume") is not None:
            r["volume"] = q["volume"]
        if q.get("sector"):  # PSX sector from /symbols
            r["sector"] = q["sector"]
        # Keep return-since-signal in step with the fresh price (factual, not a forecast).
        pas = r.get("price_at_signal")
        if pas:
            r["signal_return_pct"] = round((q["price"] - pas) / pas * 100.0, 2)
        updated += 1

    # Patch each company file's quote block too (best-effort), and recompute P/E (TTM)
    # from the fresh price so valuation stays current every refresh. pe_by_sym then flows
    # back onto the screener rows below before screener.json is written.
    company_dir = out / "company"
    patched_files = 0
    pe_by_sym: dict[str, float | None] = {}
    for sym, q in quotes.items():
        cf = safe_file(company_dir, f"{sym}.json")
        if cf is None:
            continue
        if not cf.exists():
            continue
        try:
            detail = _load(cf)
        except (json.JSONDecodeError, OSError):
            continue
        quote = dict(detail.get("quote") or {})
        quote.update({
            "price": q["price"], "prev_close": q["prev_close"],
            "change": q["change"], "change_pct": q["change_pct"],
        })
        # Only overwrite optional fields when this run actually has them (don't null out).
        for k in ("day_open", "day_high", "day_low", "volume"):
            if q.get(k) is not None:
                quote[k] = q[k]
        # P/E (TTM) from the fresh price ÷ trailing EPS (last-4-quarters, else latest annual).
        eps_ttm = _eps_ttm(detail)
        pe = _pe_ttm(q["price"], eps_ttm)
        pe_by_sym[sym] = pe
        quote["eps_ttm"] = eps_ttm
        quote["pe_ttm"] = pe
        detail["quote"] = quote
        if isinstance(detail.get("fundamentals"), dict):
            detail["fundamentals"]["pe_ttm"] = pe
        if isinstance(detail.get("ratios"), dict):
            detail["ratios"]["pe_ratio"] = pe
        if q.get("sector") and isinstance(detail.get("security"), dict):
            detail["security"]["sector"] = q["sector"]
        # Keep the company signal block's return-since in step with the fresh price too.
        sigblk = detail.get("signal")
        if isinstance(sigblk, dict) and sigblk.get("price_at_signal"):
            pas = sigblk["price_at_signal"]
            sigblk["signal_return_pct"] = round((q["price"] - pas) / pas * 100.0, 2)
        cf.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
        patched_files += 1

    # Apply the freshly-computed P/E (TTM) onto the screener rows, then persist.
    for r in rows:
        if r.get("provider_symbol") in pe_by_sym:
            r["pe_ttm"] = pe_by_sym[r["provider_symbol"]]
    screener_path.write_text(json.dumps(rows), encoding="utf-8")

    result = {"targets": len(targets), "quoted": len(quotes), "rows_updated": updated,
              "company_files": patched_files,
              "pe_computed": sum(1 for v in pe_by_sym.values() if v)}
    log.info("refresh-prices: %s", result)
    return result


def fill_missing_prices(out: Path) -> dict[str, int]:
    """Give a row a price from our OWN daily history when the live feed had none.

    PSX quotes come from the exchange portal and 70 names arrive without one. An unpriced row
    is invisible to every portfolio - it cannot be bought, so it is filtered out of the ranking
    - which is how UBL sat at rank 21 by quality and appeared in nothing. 60 SCORED companies
    were being excluded for want of a number we already hold.

    Deliberately NOT Yahoo's live quote. For UBL.KA that field reads 259.59 while Yahoo's own
    closes for the same days run 462-478 and no split is reported; the quote is simply wrong
    for these listings. The last stored close is consistent with the history every return is
    computed from, which matters more here than being an hour fresher.
    """
    path = out / "screener.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"filled": 0}

    filled = 0
    for r in rows:
        if r.get("price") is not None:
            continue
        region, symbol = str(r.get("region") or ""), str(r.get("symbol") or "")
        if not region or not symbol:
            continue
        try:
            bars = load_bars(region, symbol)
        except Exception:  # noqa: BLE001 - a missing history is not an error here
            continue
        if not bars:
            continue
        last = max(bars)
        try:
            close = float(bars[last][4])
        except (TypeError, ValueError, IndexError):
            continue
        if close <= 0:
            continue
        r["price"] = close
        # Said out loud, so a stale close is never mistaken for a live quote.
        r["price_source"] = f"last close {last}"
        filled += 1

    if filled:
        path.write_text(json.dumps(rows), encoding="utf-8")
        log.info("fill-missing-prices: %d rows priced from stored history", filled)
    return {"filled": filled}
