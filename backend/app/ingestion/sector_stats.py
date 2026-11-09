"""Sector Rotation and Company-vs-Sector, built from the published screener every Daily.

THE DEFECT. sector_stats.json was written only by the database export (services/sectors.py),
which stopped running in August. The Sector Rotation page and every company's "Company vs
Sector" card read a file last written on 22 August: 75 US financials, averages from that week,
medians from annual ratios, and no Dubai at all although the page had a Dubai tab.

THE CURE. Everything the page shows is already on the screener rows the Daily has just written:
composite, technical and fundamental scores, sector, and the TTM ratios from our own CSVs. The
one thing that is not is breadth (the share of a sector's names above their 50-day average),
and that comes from the price packs the Daily keeps current. Same shape as before, so neither
page changes.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable

MEDIANS = {"roe": "roe", "roic": "roic", "net_margin": "net_margin",
           "operating_margin": "operating_margin", "revenue_growth": "revenue_growth",
           "eps_growth": "eps_growth", "debt_to_equity": "debt_to_equity", "pe_ratio": "pe_ttm"}
MIN_NAMES = 2
SMA_DAYS = 50
NON_EQUITY = {"Forex", "Crypto", "Index", "Commodity", "ETF"}


def _f(v: object) -> float | None:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def trend_label(above: float | None) -> str:
    if above is None:
        return "—"
    if above >= 0.7:
        return "Strong"
    if above >= 0.55:
        return "Improving"
    if above >= 0.4:
        return "Neutral"
    return "Weak"


def above_sma(closes: list[float], days: int = SMA_DAYS) -> bool | None:
    """Last close above the average of the last `days`; None without enough history."""
    clean = [c for c in closes if c]
    if len(clean) < days:
        return None
    return clean[-1] > statistics.fmean(clean[-days:])


def _mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 1) if vals else None


def build(rows: list[dict], closes: Callable[[str, str], list[float]]) -> dict[str, list[dict]]:
    """{region: [sector profile, ...]}, best average composite first.

    `closes(region, symbol)` returns the packed closes oldest first, or [] when there are none.
    Only names with a composite count, so a stopped chart does not drag its sector's average.
    """
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        sector, region = r.get("sector"), r.get("region")
        if (not sector or not region or region == "global" or sector in NON_EQUITY
                or (r.get("asset_class") not in (None, "equity"))):
            continue
        if _f(r.get("composite_score")) is None:
            continue
        buckets[(region, sector)].append(r)

    out: dict[str, list[dict]] = defaultdict(list)
    for (region, sector), names in buckets.items():
        if len(names) < MIN_NAMES:
            continue
        breadth = [b for b in (above_sma(closes(region, str(n["symbol"]))) for n in names)
                   if b is not None]
        above = round(sum(breadth) / len(breadth), 2) if breadth else None
        medians: dict[str, float | None] = {}
        for key, field in MEDIANS.items():
            vals = [_f(n.get(field)) for n in names]
            # A negative P/E is a loss, not a cheap price, and would drag the median through zero.
            vals = [v for v in vals if v is not None and (key != "pe_ratio" or v > 0)]
            medians[key] = round(statistics.median(vals), 4) if vals else None
        technical = _mean(_f(n.get("technical_score")) for n in names)
        out[region].append({
            "sector": sector,
            "region": region,
            "count": len(names),
            "score": _mean(_f(n.get("composite_score")) for n in names),
            "technical": technical,
            "fundamental": _mean(_f(n.get("fundamental_score")) for n in names),
            "momentum": technical,
            "breadth_above_50dma": above,
            "trend": trend_label(above),
            "medians": medians,
        })
    for region in out:
        out[region].sort(key=lambda s: s["score"] or 0, reverse=True)
    return dict(out)
