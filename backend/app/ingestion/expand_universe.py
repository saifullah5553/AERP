"""Expand the screener universe to full US / India / Australia listings, keyless.

Pulls the full listed-company lists (SEC / NSE / ASX — all free, keyless), then for every
name NOT already in the snapshot fetches Yahoo chart-v8 daily history (reachable from CI),
computes the technical score → technical-only composite → signal, and writes a lean
company/*.json. Names that return no Yahoo data are dropped (never faked). Fundamentals stay
with the curated pipeline (S&P 500 etc.); the long tail is technical-only, like crypto.

Run per region and commit incrementally so the static snapshot grows in verifiable steps:
    python -m app.cli expand-universe --region australia
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.engines.composite.engine import WEIGHTS
from app.engines.composite.signals import derive_signal
from app.engines.technical.engine import _scoring_metrics
from app.engines.technical.indicators import compute_indicators
from app.engines.technical.scoring import score_technical
from app.ingestion.tech_refresh import fetch_history

log = get_logger(__name__)

# Technical-only names know just 1 of the 5 composite factors, so we don't let a raw technical
# score masquerade as a full composite (which would flood the top of the composite-sorted
# screener above fully-analyzed names). Shrink toward neutral 50 by the technical weight:
# only ~35% of the way from 50 to the technical reading — honest low-conviction scoring.
_TECH_W = WEIGHTS["technical"]


def _tech_only_composite(tech: float) -> float:
    return round(50.0 + (tech - 50.0) * _TECH_W, 2)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"


# ── Universe sources (symbol, name, market_code, region, provider_symbol) ─────────────
def fetch_us_symbols() -> list[dict]:
    from app.ingestion.us_universe import EXCHANGE_MAP, SECClient

    out: list[dict] = []
    for e in SECClient().fetch():
        mc = EXCHANGE_MAP.get((e.exchange or "").strip())
        if not mc:  # keep only NYSE/Nasdaq majors
            continue
        t = e.ticker.strip().upper()
        if not t or not t.replace(".", "").replace("-", "").isalnum():
            continue
        out.append({"symbol": t, "name": e.name, "market_code": mc,
                    "region": "us", "provider_symbol": t})
    return out


def _fetch_csv(url: str) -> list[dict]:
    r = httpx.get(url, headers={"User-Agent": _UA}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def fetch_nse_symbols() -> list[dict]:
    rows = _fetch_csv("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
    out: list[dict] = []
    for row in rows:
        sym = (row.get("SYMBOL") or "").strip().upper()
        series = (row.get(" SERIES") or row.get("SERIES") or "").strip()
        if not sym or (series and series != "EQ"):  # EQ = normal equity
            continue
        name = (row.get("NAME OF COMPANY") or "").strip() or sym
        out.append({"symbol": sym, "name": name, "market_code": "NSE",
                    "region": "india", "provider_symbol": f"{sym}.NS"})
    return out


def fetch_asx_symbols() -> list[dict]:
    url = ("https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file"
           "?access_token=83ff96335c2d45a094df02a206a39ff4")
    rows = _fetch_csv(url)
    out: list[dict] = []
    for row in rows:
        code = (row.get("ASX code") or row.get("ASX Code") or "").strip().upper()
        if not code or len(code) > 4:
            continue
        name = (row.get("Company name") or "").strip() or code
        out.append({"symbol": code, "name": name, "market_code": "ASX",
                    "region": "australia", "provider_symbol": f"{code}.AX"})
    return out


_LISTED_DIR = Path(__file__).resolve().parents[3] / "data" / "universe"
_LISTED_META = {
    "india": ("NSE", ".NS"),
    "australia": ("ASX", ".AX"),
    "psx": ("PSX", ".KA"),
}


def fetch_listed_symbols(region: str) -> list[dict]:
    """Companies from data/universe/<region>.csv, captured from stockanalysis's own listing.

    The exchange feeds are narrower than what we can actually score. NSE's archive carries only
    the EQ series - ~2,050 names against the 3,020 stockanalysis lists - and fundamentals come
    from stockanalysis, so a name it lists is a name we can score. Kept as a versioned file
    rather than a live fetch so CI never depends on scraping to know the universe.
    """
    meta = _LISTED_META.get(region)
    path = _LISTED_DIR / f"{region}.csv"
    if not meta or not path.exists():
        return []
    market_code, suffix = meta
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sym = (row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            # stockanalysis writes NSE's hyphens as underscores (BAJAJ_AUTO); the exchange
            # spelling is what the rest of the platform and the price feeds use.
            sym = sym.replace("_", "-") if region == "india" else sym
            out.append({"symbol": sym, "name": (row.get("name") or "").strip() or sym,
                        "market_code": market_code, "region": region,
                        "provider_symbol": f"{sym}{suffix}"})
    return out


def _norm_key(symbol: str) -> str:
    """Match spellings across sources: stockanalysis writes both NSE's '-' and '&' as '_'."""
    return symbol.upper().replace("&", "_").replace("-", "_")


def _merged(region: str, exchange_feed: Callable[[], list[dict]]) -> Callable[[], list[dict]]:
    """Exchange feed first (authoritative spelling), topped up with anything else listed."""
    def fetch() -> list[dict]:
        rows = exchange_feed()
        # Dedupe on the normalised form, not the literal symbol. stockanalysis collapses both
        # '-' and '&' to '_', so ARE_M cannot be told apart from NSE's ARE&M by spelling alone -
        # matching literally would add a second, wrongly-named row for a company we already have.
        seen = {_norm_key(r["symbol"]) for r in rows}
        for r in fetch_listed_symbols(region):
            if _norm_key(r["symbol"]) not in seen:
                seen.add(_norm_key(r["symbol"]))
                rows.append(r)
        return rows
    return fetch


_SOURCES = {
    "us": fetch_us_symbols,
    "india": _merged("india", fetch_nse_symbols),
    "australia": _merged("australia", fetch_asx_symbols),
    # PSX has no machine-readable directory we can reach - its own portal has been down for
    # stretches of this project - so the captured listing is the whole source here.
    "psx": lambda: fetch_listed_symbols("psx"),
}

# Windows can't create files whose base name is a reserved device (PRN.AX.json fails). The
# snapshot is authored on Windows, so skip those few tickers rather than crash the batch.
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
             *(f"LPT{i}" for i in range(10))}


def _reserved(provider_symbol: str) -> bool:
    return provider_symbol.split(".", 1)[0].upper() in _RESERVED


def _company_json(row: dict, price: float | None, tech: float, comp: float, sig, dates) -> dict:
    """A lean company detail (technical-only) that the company page renders without errors."""
    return {
        "security": {
            "symbol": row["symbol"], "provider_symbol": row["provider_symbol"],
            "name": row["name"], "region": row["region"], "market_code": row["market_code"],
            "asset_class": "equity", "sector": None, "currency": None,
        },
        "quote": {"price": price},
        "scores": {"technical": round(tech, 2), "composite": comp},
        "signal": {"signal_type": sig.signal.value, "label": sig.label,
                   "signal_since": dates[-1] if dates else None},
        "fundamentals": {}, "ratios": {},
        "statements": {"income": [], "balance": [], "cashflow": []},
        "patterns": [], "dividends": [], "estimates": {}, "peers": [],
        "news": [], "insider": [], "insider_summary": None, "ai_summary": None,
    }


def expand_universe(
    data_dir: str | Path, region: str, workers: int = 8, limit: int | None = None
) -> dict[str, int]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    have = {r.get("provider_symbol") for r in rows}

    source = _SOURCES[region]
    candidates = [
        c for c in source()
        if c["provider_symbol"] not in have and not _reserved(c["provider_symbol"])
    ]
    if limit is not None:
        candidates = candidates[:limit]
    log.info("expand-universe[%s]: %d new candidates", region, len(candidates))

    company_dir = out / "company"
    company_dir.mkdir(exist_ok=True)
    syms = [c["provider_symbol"] for c in candidates]
    hist: dict[str, Any] = {}
    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for sym, h in zip(syms, pool.map(lambda s: fetch_history(s, client), syms),
                              strict=False):
                if h is not None:
                    hist[sym] = h
    finally:
        client.close()

    added = 0
    for c in candidates:
        h = hist.get(c["provider_symbol"])
        if h is None:
            continue
        dates, _open, high, low, close, vol = h
        tech = score_technical(_scoring_metrics(compute_indicators(high, low, close, vol))).score
        if tech is None:
            continue
        comp = _tech_only_composite(tech)
        sig = derive_signal(comp, _TECH_W, {"technical": tech})
        price = float(close[-1])
        row = {
            "provider_symbol": c["provider_symbol"], "symbol": c["symbol"],
            "name": c["name"], "region": c["region"], "market_code": c["market_code"],
            "sector": None, "price": round(price, 4),
            "technical_score": round(tech, 2), "composite_score": comp,
            "signal": sig.signal.value, "signal_label": sig.label,
            "signal_since": dates[-1] if dates else None,
        }
        rows.append(row)
        _cf = safe_file(company_dir, f"{c['provider_symbol']}.json")
        if _cf is None:
            continue
        _cf.write_text(
            json.dumps(_company_json(c, price, tech, comp, sig, dates), ensure_ascii=False),
            encoding="utf-8",
        )
        added += 1

    rows.sort(key=lambda r: (r.get("composite_score") is not None,
                             r.get("composite_score") or 0), reverse=True)
    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    result = {"candidates": len(candidates), "with_data": len(hist), "added": added,
              "universe_total": len(rows)}
    log.info("expand-universe[%s]: %s", region, result)
    return result
