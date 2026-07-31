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
        # Keep return-since-signal in step with the fresh price (factual, not a forecast).
        pas = r.get("price_at_signal")
        if pas:
            r["signal_return_pct"] = round((q["price"] - pas) / pas * 100.0, 2)
        updated += 1
    screener_path.write_text(json.dumps(rows), encoding="utf-8")

    # Patch each company file's quote block too (best-effort).
    company_dir = out / "company"
    patched_files = 0
    for sym, q in quotes.items():
        cf = company_dir / f"{sym}.json"
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
        detail["quote"] = quote
        # Keep the company signal block's return-since in step with the fresh price too.
        sigblk = detail.get("signal")
        if isinstance(sigblk, dict) and sigblk.get("price_at_signal"):
            pas = sigblk["price_at_signal"]
            sigblk["signal_return_pct"] = round((q["price"] - pas) / pas * 100.0, 2)
        cf.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
        patched_files += 1

    result = {"targets": len(targets), "quoted": len(quotes), "rows_updated": updated,
              "company_files": patched_files}
    log.info("refresh-prices: %s", result)
    return result
