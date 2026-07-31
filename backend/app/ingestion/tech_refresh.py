"""Daily all-market technical → composite → signal recompute (Yahoo chart-v8 history).

The free CI refresh can't run yfinance (429), so non-PSX scores were frozen between local
rebuilds. But chart-v8 returns full daily HISTORY from CI, and the technical scorer is a pure
function — so we can recompute the technical leg daily, reblend the composite with the
committed fundamental/momentum/quality/risk scores + the macro-regime overlay, re-derive the
signal, and patch the snapshot (screener.json + company/*.json). Also feeds movers.json so
upgrades/downgrades appear across all markets. PSX is handled by the main pipeline.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.core.logging import get_logger
from app.engines.composite.engine import WEIGHTS
from app.engines.composite.regime_modifier import apply_regime_modifier
from app.engines.composite.signals import derive_signal
from app.engines.technical.engine import _scoring_metrics
from app.engines.technical.indicators import compute_indicators
from app.engines.technical.scoring import score_technical

log = get_logger(__name__)

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
_UA = "Mozilla/5.0 (compatible; AERP/1.0)"
MIN_BARS = 60


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def fetch_history(sym: str, client: httpx.Client):
    """chart-v8 daily OHLCV → (high, low, close, volume) numpy arrays, or None."""
    try:
        resp = client.get(_CHART.format(sym=sym), headers={"User-Agent": _UA}, timeout=20)
        resp.raise_for_status()
        res = resp.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        highs, lows, closes, vols = q.get("high"), q.get("low"), q.get("close"), q.get("volume")
        if not closes:
            return None
        bars = [
            (highs[i], lows[i], closes[i], vols[i] if vols else None)
            for i in range(len(closes))
            if closes[i] is not None
        ]
        if len(bars) < MIN_BARS:
            return None
        close = np.array([b[2] for b in bars], dtype=float)
        high = np.array([b[0] if b[0] is not None else b[2] for b in bars], dtype=float)
        low = np.array([b[1] if b[1] is not None else b[2] for b in bars], dtype=float)
        vol = np.array([b[3] if b[3] is not None else 0.0 for b in bars], dtype=float)
        return high, low, close, vol
    except Exception:  # noqa: BLE001 - one bad symbol shouldn't stop the batch
        return None


def _reblend(fund, tech, mom, qual, risk) -> tuple[float | None, float, dict]:
    comps = {"fundamental": fund, "technical": tech, "momentum": mom, "quality": qual, "risk": risk}
    present = {k: v for k, v in comps.items() if v is not None}
    anchor = comps["fundamental"] is not None or comps["technical"] is not None
    if not present or not anchor:
        return None, 0.0, {}
    total_w = sum(WEIGHTS[k] for k in present)
    base = round(sum(v * WEIGHTS[k] for k, v in present.items()) / total_w, 2)
    return base, round(total_w, 4), present


def refresh_technicals(
    data_dir: str | Path,
    skip_regions: tuple[str, ...] = ("psx",),
    workers: int = 8,
    limit: int | None = None,
) -> dict[str, int]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    try:
        _reg = json.loads((out / "macro_regime.json").read_text(encoding="utf-8"))
        regime_map = _reg.get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}

    targets = [r for r in rows if r.get("region") not in skip_regions and r.get("provider_symbol")]
    if limit is not None:
        targets = targets[:limit]

    syms = [r["provider_symbol"] for r in targets]
    hist: dict[str, Any] = {}
    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = pool.map(lambda s: fetch_history(s, client), syms)
            for sym, h in zip(syms, results, strict=False):
                if h is not None:
                    hist[sym] = h
    finally:
        client.close()

    company = out / "company"
    today = datetime.now(UTC).date().isoformat()
    updated = 0
    deltas: dict[str, dict] = {}

    for r in targets:
        sym = r["provider_symbol"]
        h = hist.get(sym)
        if h is None:
            continue
        high, low, close, vol = h
        tech = score_technical(_scoring_metrics(compute_indicators(high, low, close, vol))).score
        if tech is None:
            continue
        # Committed non-technical legs from the company file (fall back to the screener row).
        sc: dict = {}
        cf = company / f"{sym}.json"
        if cf.exists():
            try:
                sc = json.loads(cf.read_text(encoding="utf-8")).get("scores") or {}
            except (OSError, json.JSONDecodeError):
                sc = {}
        fund = _f(sc.get("fundamental"))
        if fund is None:
            fund = _f(r.get("fundamental_score"))
        base, coverage, present = _reblend(fund, _f(tech), _f(sc.get("momentum")),
                                           _f(sc.get("quality")), _f(sc.get("risk")))
        if base is None:
            continue
        composite, _bd = apply_regime_modifier(
            base, regime_map.get(r.get("region")), _f(r.get("debt_to_equity"))
        )
        sig = derive_signal(composite, coverage, present)

        old = r.get("composite_score")
        r["technical_score"] = round(tech, 2)
        r["composite_score"] = composite
        r["signal"] = sig.signal.value
        r["signal_label"] = sig.label

        if old is not None and abs(composite - old) >= 1.0:
            deltas[sym] = {
                "provider_symbol": sym, "symbol": r.get("symbol"), "name": r.get("name"),
                "region": r.get("region"), "composite": composite, "prev": old,
                "delta": round(composite - old, 2), "fundamental": r.get("fundamental_score"),
                "technical": round(tech, 2), "date": today,
            }

        if cf.exists():
            try:
                d = json.loads(cf.read_text(encoding="utf-8"))
                if isinstance(d.get("scores"), dict):
                    d["scores"]["technical"] = round(tech, 2)
                    d["scores"]["composite"] = composite
                if isinstance(d.get("signal"), dict):
                    d["signal"]["signal_type"] = sig.signal.value
                    d["signal"]["label"] = sig.label
                cf.write_text(json.dumps(d), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        updated += 1

    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    _update_movers(out, deltas, today)

    result = {
        "targets": len(targets), "quoted": len(hist),
        "updated": updated, "movers": len(deltas),
    }
    log.info("refresh-technicals: %s", result)
    return result


def _update_movers(out: Path, deltas: dict[str, dict], today: str) -> None:
    path = out / "movers.json"
    recent: dict[str, dict] = {}
    if path.exists():
        try:
            for m in json.loads(path.read_text(encoding="utf-8")).get("all", []):
                recent[m.get("provider_symbol")] = m
        except (OSError, json.JSONDecodeError):
            pass
    cutoff = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
    recent = {k: v for k, v in recent.items() if (v.get("date") or "") >= cutoff}
    recent.update(deltas)
    allm = sorted(recent.values(), key=lambda m: (m.get("date") or ""), reverse=True)
    path.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "upgrades": sorted([m for m in allm if m["delta"] > 0], key=lambda m: -m["delta"]),
        "downgrades": sorted([m for m in allm if m["delta"] < 0], key=lambda m: m["delta"]),
        "all": allm,
    }), encoding="utf-8")
