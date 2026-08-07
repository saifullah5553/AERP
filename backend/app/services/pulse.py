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
    "gcc": "Saudi (Tadawul)",
    "dfm": "Dubai (DFM)",
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


def pulse_from_pairs(pairs: list[tuple]) -> list[dict]:
    """Aggregate (region, composite, change_pct) rows into one pulse row per region.

    Two different readings of a market, kept apart on purpose. Sentiment (bullish/bearish) is
    the composite score - our opinion of the names. Breadth (advancers/decliners) is what
    prices actually did today. They disagree constantly, and conflating them is how a stock
    down 0.97% ended up filed under the up arrow because its composite was 85.
    """
    groups: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
    for row in pairs:
        # (region, composite) is still accepted: breadth is an addition, and a caller that
        # only knows about sentiment should keep working rather than raise.
        region, comp = row[0], row[1]
        change = row[2] if len(row) > 2 else None
        groups[region].append((
            float(comp) if comp is not None else None,
            float(change) if change is not None else None,
        ))

    out: list[dict] = []
    for region in _ORDER:
        items = groups.get(region)
        if not items:
            continue
        comps = [c for c, _ in items if c is not None]
        if not comps:
            continue
        # Counted over every row in the market, including names with no composite: whether a
        # price rose has nothing to do with whether we managed to score it.
        advancers = sum(1 for _, ch in items if ch is not None and ch > 0)
        decliners = sum(1 for _, ch in items if ch is not None and ch < 0)
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
            "advancers": advancers,
            "decliners": decliners,
        })
    return out


def compute_pulse(db: Session) -> list[dict]:
    """One pulse row per market region (live path)."""
    rows, _ = query_screener(
        db, ScreenerFilters(min_composite=0, sort_by="composite_score"), 0, 20000
    )
    return pulse_from_pairs(
        [(r.region.value, r.composite_score, getattr(r, "change_pct", None)) for r in rows]
    )


def pulse_from_screener_dicts(rows: list[dict]) -> list[dict]:
    """One pulse row per region from exported screener dicts (static path)."""
    def region_of(r: dict) -> str:
        reg = r.get("region")
        return reg.value if hasattr(reg, "value") else str(reg)
    return pulse_from_pairs(
        [(region_of(r), r.get("composite_score"), r.get("change_pct")) for r in rows]
    )
