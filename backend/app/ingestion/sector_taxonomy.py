"""One sector vocabulary for every market.

Sectors arrived from four sources that do not agree, and the result was 97 distinct values for
what should be about a dozen:

  * two competing taxonomies - Yahoo's ("Consumer Cyclical", "Healthcare") on 7,360 rows and
    GICS's ("Consumer Discretionary", "Health Care") on 347. Both correct, neither compatible.
  * 21 pairs differing only in case - "Cement" and "CEMENT" as separate sectors.
  * PSX's own exchange categories, which are not sectors at all. "Modarabas", "Textile
    Spinning" and "Sugar & Allied Industries" are industries; the sector is Financial Services,
    Consumer Cyclical, Consumer Defensive.

A fragmented vocabulary is quietly destructive: the sector filter splits one sector across
several entries, and sector rotation compares groups that are not comparable.

Yahoo's vocabulary wins on weight of evidence - it covers 20x more rows - so everything maps
onto it. A PSX category keeps its detail by moving to `industry`, where it belongs, rather than
being thrown away.
"""

from __future__ import annotations

# The complete set. Anything outside this is a mapping bug, not a new sector.
CANONICAL: frozenset[str] = frozenset({
    "Basic Materials", "Communication Services", "Consumer Cyclical", "Consumer Defensive",
    "Energy", "Financial Services", "Healthcare", "Industrials", "Real Estate",
    "Technology", "Utilities",
    # Instruments that are not companies.
    "Forex", "Crypto", "Index", "Commodity", "ETF",
})

# GICS -> Yahoo. Same concept, different house style.
_GICS = {
    "consumer discretionary": "Consumer Cyclical",
    "consumer staples": "Consumer Defensive",
    "information technology": "Technology",
    "health care": "Healthcare",
    "financials": "Financial Services",
    "materials": "Basic Materials",
    "consumer durables & apparel": "Consumer Cyclical",
    "consumer services": "Consumer Cyclical",
    "capital goods": "Industrials",
    "telecommunication services": "Communication Services",
    "media & entertainment": "Communication Services",
    "software & services": "Technology",
    "technology hardware & equipment": "Technology",
    "banks": "Financial Services",
    "diversified financials": "Financial Services",
    "insurance": "Financial Services",
    "pharmaceuticals, biotechnology & life sciences": "Healthcare",
    "health care equipment & services": "Healthcare",
    "food, beverage & tobacco": "Consumer Defensive",
    "food & staples retailing": "Consumer Defensive",
    "household & personal products": "Consumer Defensive",
    "retailing": "Consumer Cyclical",
    "automobiles & components": "Consumer Cyclical",
    "commercial & professional services": "Industrials",
    "transportation": "Industrials",
    "real estate management & development": "Real Estate",
    "semiconductors & semiconductor equipment": "Technology",
    "energy": "Energy",
    "utilities": "Utilities",
}

# PSX exchange categories. These are industries; the value here is the sector they belong to,
# and the original is preserved as the industry.
_PSX = {
    "textile composite": "Consumer Cyclical",
    "textile spinning": "Consumer Cyclical",
    "textile weaving": "Consumer Cyclical",
    "woollen": "Consumer Cyclical",
    "jute": "Consumer Cyclical",
    "synthetic & rayon": "Consumer Cyclical",
    "leather & tanneries": "Consumer Cyclical",
    "apparel": "Consumer Cyclical",
    "automobile assembler": "Consumer Cyclical",
    "automobile parts & accessories": "Consumer Cyclical",
    "inv. banks / inv. cos. / securities cos.": "Financial Services",
    "commercial banks": "Financial Services",
    "modarabas": "Financial Services",
    "leasing companies": "Financial Services",
    "food & personal care products": "Consumer Defensive",
    "sugar & allied industries": "Consumer Defensive",
    "vanaspati & allied industries": "Consumer Defensive",
    "tobacco": "Consumer Defensive",
    "chemical": "Basic Materials",
    "cement": "Basic Materials",
    "paper, board & packaging": "Basic Materials",
    "glass & ceramics": "Basic Materials",
    "fertilizer": "Basic Materials",
    "technology & communication": "Technology",
    "power generation & distribution": "Utilities",
    "pharmaceuticals": "Healthcare",
    "engineering": "Industrials",
    "transport": "Industrials",
    "cable & electrical goods": "Industrials",
    "real estate investment trust": "Real Estate",
    "property": "Real Estate",
    "oil & gas marketing companies": "Energy",
    "oil & gas exploration companies": "Energy",
    "refinery": "Energy",
    # "Miscellaneous" says nothing. Left unmapped so it surfaces for a human rather than
    # being filed under a sector nobody chose.
}

# Fund categories that arrived in a sector field, plus a few strays from the ASX feed.
_FUND_AND_STRAY = {
    "us equity": "ETF", "global equity": "ETF", "thematic": "ETF", "sector": "ETF",
    "fixed income": "ETF", "multi-asset": "ETF",
    "precious metals": "Basic Materials", "industrial metals": "Basic Materials",
    "agriculture": "Consumer Defensive",
}

# Values that name nothing. Cleared rather than mapped, so they surface for a human instead of
# sitting under a sector nobody chose - "Miscellaneous" is not an answer.
MEANINGLESS: frozenset[str] = frozenset({"miscellaneous", "class pend", "n/a", "none", "other"})

_ALIASES: dict[str, str] = {**_GICS, **_PSX, **_FUND_AND_STRAY}
# Exchange categories worth keeping as an industry when we replace them with a sector.
_KEEPS_INDUSTRY = frozenset(_PSX)


def canonical_sector(value: str | None) -> str | None:
    """The one true spelling for a sector, or None if it cannot be mapped."""
    if not value:
        return None
    raw = " ".join(str(value).split())
    low = raw.lower()

    for known in CANONICAL:  # already canonical, whatever its case
        if low == known.lower():
            return known
    return _ALIASES.get(low)


def industry_for(value: str | None) -> str | None:
    """The industry implied by an exchange category, title-cased.

    PSX reports "TEXTILE SPINNING" as a sector. It is an industry, and it is real detail - so
    it moves rather than being discarded when the sector is canonicalised.
    """
    if not value:
        return None
    raw = " ".join(str(value).split())
    if raw.lower() not in _KEEPS_INDUSTRY:
        return None
    # Capitalise the first letter of each word, keeping punctuation in place - "paper," and
    # "inv." are words too, and `str.isalpha` is False for both.
    small = {"and", "of", "&", "/"}
    parts = [w if w in small else (w[:1].upper() + w[1:]) for w in raw.lower().split(" ")]
    return " ".join(parts)


def normalize_rows(rows: list[dict]) -> dict[str, int]:
    """Canonicalise `sector` across the universe, moving exchange detail into `industry`."""
    changed = industry_added = unmapped = cleared = 0
    unknown: set[str] = set()
    for r in rows:
        current = r.get("sector")
        if not current:
            continue
        if " ".join(str(current).split()).lower() in MEANINGLESS:
            r["sector"] = None
            cleared += 1
            continue
        canon = canonical_sector(current)
        if canon is None:
            unmapped += 1
            unknown.add(str(current))
            continue
        industry = industry_for(current)
        if industry and not r.get("industry"):
            r["industry"] = industry
            industry_added += 1
        if canon != current:
            r["sector"] = canon
            changed += 1
    return {"changed": changed, "industry_added": industry_added, "cleared": cleared,
            "unmapped": unmapped, "unmapped_values": len(unknown)}
