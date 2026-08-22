"""Sector profiles built from the SNAPSHOT, for markets the database never sees.

`build_sector_stats` reads the database. The static pipeline only ever populates PSX there, so
every other market's sector rotation is whatever was last written by a database-backed run -
and Dubai, which was added after that, has never appeared on the page AT ALL. Five regions
show, six exist. `_merge_sector_stats` then carries the five forward on every refresh, so
nothing ever looked broken; the sixth was simply absent, and an absence draws no attention.

This is the same repair already applied to the market regime: compute from the snapshot, which
carries region, sector, the scores and the prices for all six markets, and fall back to it for
any region the database path did not produce. The database remains authoritative where it
answers - this only fills the silence.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

MIN_SECTOR_COUNT = 2
MA_WINDOW = 50


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _med(vals: list[float | None]) -> float | None:
    clean = [v for v in vals if v is not None]
    return round(median(clean), 4) if clean else None


def _trend(breadth: float | None) -> str:
    if breadth is None:
        return "Unknown"
    if breadth >= 0.66:
        return "Strong"
    if breadth >= 0.40:
        return "Mixed"
    return "Weak"


def _above_50dma(region: str, symbols: list[str]) -> dict[str, bool]:
    """Which of these symbols trade above their own 50-day average."""
    from app.ingestion.price_pack import load_packed

    packed = load_packed(region)
    out: dict[str, bool] = {}
    for sym in symbols:
        key = str(sym).upper().replace("/", "_").replace(":", "_")
        series = packed.get(key)
        if not series or len(series) < MA_WINDOW:
            continue
        days = sorted(series)[-MA_WINDOW:]
        closes = [series[d] for d in days]
        ma = sum(closes) / len(closes)
        if ma > 0:
            out[sym] = closes[-1] > ma
    return out


def sector_stats_for_region(rows: list[dict], region: str) -> list[dict]:
    """Sector profiles for one market, in the same shape the database path emits."""
    equities = [r for r in rows
                if r.get("region") == region
                and (r.get("asset_class") or "equity") == "equity"
                and r.get("sector")]
    if not equities:
        return []

    above = _above_50dma(region, [str(r["symbol"]) for r in equities if r.get("symbol")])

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in equities:
        buckets[str(r["sector"])].append(r)

    out: list[dict] = []
    for sector, members in buckets.items():
        if len(members) < MIN_SECTOR_COUNT:
            continue
        flags = [above[str(m["symbol"])] for m in members
                 if m.get("symbol") and str(m["symbol"]) in above]
        breadth = (sum(1 for f in flags if f) / len(flags)) if flags else None
        out.append({
            "sector": sector,
            "region": region,
            "count": len(members),
            "score": _med([_f(m.get("composite_score")) for m in members]),
            "technical": _med([_f(m.get("technical_score")) for m in members]),
            "fundamental": _med([_f(m.get("quality_score")) for m in members]),
            "pabrai": _med([_f(m.get("pabrai_score")) for m in members]),
            "momentum": _med([_f(m.get("technical_score")) for m in members]),
            "breadth_above_50dma": round(breadth, 4) if breadth is not None else None,
            "trend": _trend(breadth),
            "medians": {
                "roe": _med([_f(m.get("roe")) for m in members]),
                "roic": _med([_f(m.get("roic")) for m in members]),
                "net_margin": _med([_f(m.get("net_margin")) for m in members]),
                "operating_margin": _med([_f(m.get("operating_margin")) for m in members]),
                "revenue_growth": _med([_f(m.get("revenue_growth")) for m in members]),
                "eps_growth": _med([_f(m.get("eps_growth")) for m in members]),
                "debt_to_equity": _med([_f(m.get("debt_to_equity")) for m in members]),
                "pe_ratio": _med([_f(m.get("pe_ratio")) for m in members]),
            },
        })
    out.sort(key=lambda s: (s.get("score") is not None, s.get("score") or 0), reverse=True)
    return out


def fill_missing_regions(stats: dict[str, list[dict]], rows: list[dict],
                         regions: tuple[str, ...]) -> dict[str, list[dict]]:
    """Add a snapshot-built profile for every region the database path left empty."""
    out = dict(stats or {})
    added = []
    for region in regions:
        if out.get(region):
            continue
        built = sector_stats_for_region(rows, region)
        if built:
            out[region] = built
            added.append(f"{region}({len(built)})")
    if added:
        log.info("sector-stats: built from the snapshot for %s", ", ".join(added))
    return out
