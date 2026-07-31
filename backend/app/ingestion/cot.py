"""Commitment of Traders (COT) — CFTC weekly Legacy report for commodities & FX.

Free, keyless U.S. government data (publicreporting.cftc.gov Socrata API), reachable from
CI. For each tracked futures/currency we surface the NON-COMMERCIAL (large speculator =
"smart money") positioning: net long/short, whether that net is increasing (buying) or
decreasing (selling) vs the prior week, and whether total open interest is rising/falling.

Mapping is by a distinctive substring + we pick the matched contract with the highest open
interest, which robustly selects the main contract (e.g. COMEX Gold over "PAX GOLD PERP").
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
_UA = "Mozilla/5.0 (compatible; AERP/1.0)"

# provider_symbol -> (display label, distinctive substring in the CFTC market name)
COT_MAP: dict[str, tuple[str, str]] = {
    # commodities
    "GC=F": ("Gold", "GOLD"), "SI=F": ("Silver", "SILVER"),
    "HG=F": ("Copper", "COPPER"), "PL=F": ("Platinum", "PLATINUM"),
    "PA=F": ("Palladium", "PALLADIUM"), "CL=F": ("WTI Crude", "CRUDE OIL, LIGHT SWEET"),
    "BZ=F": ("Brent Crude", "BRENT"), "NG=F": ("Natural Gas", "NATURAL GAS"),
    "RB=F": ("Gasoline RBOB", "GASOLINE RBOB"), "HO=F": ("Heating Oil/ULSD", "ULSD"),
    "ZC=F": ("Corn", "CORN"), "ZW=F": ("Wheat", "WHEAT"), "ZS=F": ("Soybeans", "SOYBEANS"),
    "KC=F": ("Coffee", "COFFEE"), "SB=F": ("Sugar", "SUGAR NO. 11"),
    "CT=F": ("Cotton", "COTTON NO. 2"), "CC=F": ("Cocoa", "COCOA"),
    "LE=F": ("Live Cattle", "LIVE CATTLE"),
    # FX (CFTC currency futures are the named currency vs USD)
    "EURUSD=X": ("Euro FX", "EURO FX"), "GBPUSD=X": ("British Pound", "BRITISH POUND"),
    "USDJPY=X": ("Japanese Yen", "JAPANESE YEN"), "USDCHF=X": ("Swiss Franc", "SWISS FRANC"),
    "USDCAD=X": ("Canadian Dollar", "CANADIAN DOLLAR"),
    "AUDUSD=X": ("Australian Dollar", "AUSTRALIAN DOLLAR"),
    "NZDUSD=X": ("New Zealand Dollar", "NEW ZEALAND DOLLAR"),
    "USDMXN=X": ("Mexican Peso", "MEXICAN PESO"),
    "USDBRL=X": ("Brazilian Real", "BRAZILIAN REAL"),
    "USDZAR=X": ("South African Rand", "SOUTH AFRICAN RAND"),
}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class CFTCClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(headers={"User-Agent": _UA}, timeout=30.0)

    def recent(self, limit: int = 6000) -> list[dict]:
        """Recent Legacy futures-only rows (all markets), newest first."""
        params = {
            "$select": (
                "market_and_exchange_names,report_date_as_yyyy_mm_dd,open_interest_all,"
                "noncomm_positions_long_all,noncomm_positions_short_all"
            ),
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(limit),
        }
        resp = self._client.get(_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def _trend(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "flat"
    if cur > prev:
        return "increasing"
    if cur < prev:
        return "decreasing"
    return "flat"


def build_cot(client: CFTCClient | None = None) -> dict[str, dict]:
    client = client or CFTCClient()
    try:
        rows = client.recent()
    except Exception as exc:  # noqa: BLE001 - network optional
        log.warning("COT fetch failed: %s", exc)
        return {}

    out: dict[str, dict] = {}
    for sym, (label, sub) in COT_MAP.items():
        # All rows whose market name contains the substring, grouped by market name.
        by_market: dict[str, list[dict]] = {}
        for r in rows:
            name = r.get("market_and_exchange_names") or ""
            if sub in name.upper():
                by_market.setdefault(name, []).append(r)
        if not by_market:
            continue
        # Pick the contract with the highest latest open interest (the main one).
        def _oi0(name: str, bm: dict = by_market) -> float:
            return _num(bm[name][0].get("open_interest_all")) or 0

        best_name = max(by_market, key=_oi0)
        series = sorted(
            by_market[best_name],
            key=lambda r: r.get("report_date_as_yyyy_mm_dd", ""),
            reverse=True,
        )
        latest = series[0]
        prev = series[1] if len(series) > 1 else {}

        nl = _num(latest.get("noncomm_positions_long_all"))
        ns = _num(latest.get("noncomm_positions_short_all"))
        oi = _num(latest.get("open_interest_all"))
        if nl is None or ns is None:
            continue
        net = nl - ns
        pl = _num(prev.get("noncomm_positions_long_all"))
        ps = _num(prev.get("noncomm_positions_short_all"))
        net_prev = (pl - ps) if (pl is not None and ps is not None) else None
        net_trend = _trend(net, net_prev)
        flow = ("Buying" if net_trend == "increasing"
                else "Selling" if net_trend == "decreasing" else "Neutral")

        out[sym] = {
            "label": label,
            "contract": best_name,
            "report_date": (latest.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "nc_long": int(nl), "nc_short": int(ns),
            "net": int(net),
            "pct_long": round(nl / (nl + ns) * 100, 1) if (nl + ns) else None,
            "oi": int(oi) if oi is not None else None,
            "stance": "Net Long" if net > 0 else "Net Short" if net < 0 else "Flat",
            "flow": flow,
            "net_trend": net_trend,
            "oi_trend": _trend(oi, _num(prev.get("open_interest_all"))),
        }
    log.info("COT: %d instruments", len(out))
    return out
