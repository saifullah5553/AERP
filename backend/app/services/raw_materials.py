"""Raw-material cost-trend intelligence for the company research page.

Professional investors watch input costs *before* results land. We already ingest
liquid commodity futures (Yahoo ``=F``); this module classifies each commodity's
current trend from its own moving averages (no prediction, just direction of the
real series) and maps company sectors to the commodities that are genuine cost
drivers. The per-company margin impact is a deterministic rule — a company that
*consumes* an input benefits when that input's price falls — not a forecast.

Output is baked into ``raw_materials.json`` (global, sector-keyed) so the frontend
can attach the right materials to any company by its sector without a per-company
recompute.
"""

from __future__ import annotations

import json
from pathlib import Path

# Tracked commodity symbol → display name. Only liquid futures we actually ingest.
COMMODITY_NAMES: dict[str, str] = {
    "GC": "Gold", "SI": "Silver", "PL": "Platinum", "PA": "Palladium",
    "HG": "Copper", "CL": "Crude Oil (WTI)", "BZ": "Brent Crude",
    "NG": "Natural Gas", "RB": "Gasoline", "HO": "Heating Oil",
    "ZC": "Corn", "ZW": "Wheat", "ZS": "Soybeans", "KC": "Coffee",
    "SB": "Sugar", "CC": "Cocoa", "CT": "Cotton", "LE": "Live Cattle",
}

# Sector/industry keyword (lower-case, substring match) → cost-driver commodities,
# most-relevant first. Keys cover GICS (US/curated) and PSX portal sector names.
SECTOR_INPUTS: list[tuple[tuple[str, ...], list[str]]] = [
    (("cement",), ["NG", "CL"]),
    (("fertil",), ["NG"]),
    (("chemical", "petrochemical"), ["CL", "NG"]),
    (("textile", "spinning", "synthetic", "rayon", "apparel"), ["CT", "CL"]),
    (("sugar",), ["SB"]),
    (("food", "personal care", "consumer staples", "consumer defensive",
      "beverage", "tobacco"), ["ZW", "ZC", "SB", "ZS"]),
    (("agri", "agriculture"), ["ZC", "ZW", "ZS"]),
    (("oil & gas", "oil and gas", "petroleum", "refinery", "energy"), ["CL", "NG"]),
    (("power", "utilit"), ["NG", "CL"]),
    (("glass", "ceramic"), ["NG"]),
    (("automobile", "auto ", "auto,", "autos", "vehicle"), ["HG", "CL"]),
    (("engineering", "steel", "iron", "metal"), ["HG"]),
    (("airline", "transport", "logistics", "shipping", "aviation"), ["CL"]),
    (("paper", "board", "packaging"), ["NG"]),
    (("materials",), ["HG", "CL"]),
]


def classify_trend(close: float | None, sma50: float | None, sma200: float | None) -> str:
    """Direction of the real price series from its moving averages."""
    if close and sma50 and sma200:
        if close < sma50 < sma200:
            return "decreasing"
        if close > sma50 > sma200:
            return "increasing"
    if close and sma50:
        if close < sma50 * 0.98:
            return "decreasing"
        if close > sma50 * 1.02:
            return "increasing"
    return "sideways"


def _read_commodity(company_dir: Path, symbol: str) -> dict | None:
    """Read a commodity company JSON (provider_symbol is ``SYMBOL=F``)."""
    path = company_dir / f"{symbol}=F.json"
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    q = d.get("quote") or {}
    t = d.get("technical") or {}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    close = num(q.get("price"))
    trend = classify_trend(close, num(t.get("sma_50")), num(t.get("sma_200")))
    return {
        "symbol": symbol,
        "name": COMMODITY_NAMES.get(symbol, symbol),
        "trend": trend,
        "change_pct": num(q.get("change_pct")),
        "close": close,
    }


def build_raw_materials(company_dir: Path) -> dict:
    """Global raw-material trend map, built from committed commodity JSONs."""
    commodities: dict[str, dict] = {}
    for sym in COMMODITY_NAMES:
        row = _read_commodity(company_dir, sym)
        if row is not None:
            commodities[sym] = row

    sector_map = [
        {"keywords": list(keys), "materials": [m for m in mats if m in commodities]}
        for keys, mats in SECTOR_INPUTS
    ]
    sector_map = [s for s in sector_map if s["materials"]]

    # Aggregate outlook from how many tracked inputs are falling vs rising.
    trends = [c["trend"] for c in commodities.values()]
    down = trends.count("decreasing")
    up = trends.count("increasing")
    if down > up + 2:
        outlook = ("Input-cost environment is broadly improving — a majority of "
                   "tracked commodity inputs are declining, which is supportive of "
                   "gross margins across cost-sensitive sectors.")
    elif up > down + 2:
        outlook = ("Input-cost environment is worsening — a majority of tracked "
                   "commodity inputs are rising, which pressures gross margins in "
                   "cost-sensitive sectors.")
    else:
        outlook = ("Input-cost environment is mixed — commodity input trends are "
                   "divergent, so margin impact is company- and sector-specific.")

    return {
        "commodities": commodities,
        "sector_map": sector_map,
        "outlook": outlook,
        "counts": {"decreasing": down, "increasing": up, "sideways": trends.count("sideways")},
    }
