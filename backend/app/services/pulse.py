"""Market pulse — a bullish / bearish / neutral read per market.

Aggregates the latest composite scores of every scored security in a market into
a single sentiment label plus breadth (how many names are bullish vs bearish). The
screener already resolves latest-composite per security, so we build on it rather
than re-deriving the join.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.services.screener import ScreenerFilters, query_screener

# Region → display label + ordering for the pulse strip.
REGION_LABELS: dict[str, str] = {
    "us": "US",
    "psx": "Pakistan",
    "india": "India",
    "gcc": "GCC",
    "australia": "Australia",
    "global": "Global",
}
_ORDER = list(REGION_LABELS.keys())

BULL_CUTOFF = 60.0  # a name is "bullish" at/above this composite
BEAR_CUTOFF = 40.0  # "bearish" at/below this


def _label(avg: float) -> str:
    if avg >= 55.0:
        return "bullish"
    if avg <= 45.0:
        return "bearish"
    return "neutral"


def pulse_from_pairs(pairs: list[tuple[str, float]]) -> list[dict]:
    """Aggregate (region, composite) pairs into one pulse row per region."""
    groups: dict[str, list[float]] = defaultdict(list)
    for region, comp in pairs:
        if comp is not None:
            groups[region].append(float(comp))

    out: list[dict] = []
    for region in _ORDER:
        comps = groups.get(region)
        if not comps:
            continue
        n = len(comps)
        avg = sum(comps) / n
        bullish = sum(1 for c in comps if c >= BULL_CUTOFF)
        bearish = sum(1 for c in comps if c <= BEAR_CUTOFF)
        out.append({
            "region": region,
            "label": REGION_LABELS[region],
            "pulse": _label(avg),
            "avg_composite": round(avg, 1),
            "count": n,
            "bullish": bullish,
            "bearish": bearish,
            "neutral": n - bullish - bearish,
        })
    return out


def compute_pulse(db: Session) -> list[dict]:
    """One pulse row per market region (live path)."""
    rows, _ = query_screener(
        db, ScreenerFilters(min_composite=0, sort_by="composite_score"), 0, 20000
    )
    return pulse_from_pairs([(r.region.value, r.composite_score) for r in rows])


def pulse_from_screener_dicts(rows: list[dict]) -> list[dict]:
    """One pulse row per region from exported screener dicts (static path)."""
    def region_of(r: dict) -> str:
        reg = r.get("region")
        return reg.value if hasattr(reg, "value") else str(reg)
    return pulse_from_pairs([(region_of(r), r.get("composite_score")) for r in rows])
