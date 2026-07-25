"""Configurable market + sector benchmark profiles.

Thresholds are expressed in the SAME units the platform stores ratios in — fractions
for percentages (ROE 0.18 = 18%), plain ratios for the rest (D/E, P/E). Each metric
has a ``(good, great)`` band; ``METRIC_DIRECTION`` says whether higher or lower is
better. Everything here is data, not logic — tune freely or add markets/sectors.

Country bands are calibrated to each market's structural context rather than a single
global standard (e.g. Pakistan's higher rate/inflation regime demands a higher ROE and
earnings-yield bar and lower P/E norms than the US). These are researched, reasonable
starting points — not hard-coded universal truths — and are meant to be refined.
"""

from __future__ import annotations

# higher-is-better unless listed here.
METRIC_DIRECTION: dict[str, str] = {
    "debt_to_equity": "lower", "net_debt_to_ebitda": "lower",
    "pe": "lower", "ev_ebitda": "lower", "pb": "lower", "peg": "lower",
    "accrual_ratio": "lower",
}

# region → metric → (good, great)
_DEFAULT: dict[str, tuple[float, float]] = {
    "roe": (0.14, 0.24), "roic": (0.12, 0.20), "roce": (0.12, 0.20),
    "gross_margin": (0.25, 0.45), "operating_margin": (0.12, 0.22), "net_margin": (0.08, 0.16),
    "debt_to_equity": (1.0, 0.4), "interest_coverage": (5, 12), "net_debt_to_ebitda": (2.5, 1.0),
    "current_ratio": (1.3, 2.0),
    "revenue_cagr": (0.08, 0.16), "eps_cagr": (0.10, 0.18), "fcf_margin": (0.08, 0.16),
    "pe": (18, 11), "ev_ebitda": (12, 7), "pb": (3.0, 1.5), "peg": (1.5, 0.9),
    "fcf_yield": (0.05, 0.09), "earnings_yield": (0.06, 0.10), "dividend_yield": (0.02, 0.05),
}

COUNTRY_PROFILES: dict[str, dict[str, tuple[float, float]]] = {
    "DEFAULT": _DEFAULT,
    # Pakistan — high rate/inflation regime: higher return + yield bar, lower P/E norms.
    "PK": {
        "roe": (0.18, 0.28), "roic": (0.15, 0.25), "roce": (0.15, 0.25),
        "gross_margin": (0.20, 0.40), "operating_margin": (0.12, 0.22), "net_margin": (0.10, 0.20),
        "debt_to_equity": (0.6, 0.3), "interest_coverage": (4, 8), "net_debt_to_ebitda": (2.5, 1.0),
        "current_ratio": (1.2, 1.8),
        "revenue_cagr": (0.12, 0.22), "eps_cagr": (0.12, 0.24), "fcf_margin": (0.08, 0.15),
        "pe": (10, 6), "ev_ebitda": (7, 4), "pb": (1.5, 1.0), "peg": (1.0, 0.6),
        "fcf_yield": (0.09, 0.16), "earnings_yield": (0.12, 0.20), "dividend_yield": (0.06, 0.10),
    },
    "US": {
        "roe": (0.15, 0.25), "roic": (0.12, 0.20), "roce": (0.12, 0.20),
        "gross_margin": (0.30, 0.55), "operating_margin": (0.14, 0.25), "net_margin": (0.10, 0.20),
        "debt_to_equity": (1.0, 0.4), "interest_coverage": (6, 14), "net_debt_to_ebitda": (3.0, 1.0),
        "current_ratio": (1.3, 2.0),
        "revenue_cagr": (0.08, 0.16), "eps_cagr": (0.10, 0.20), "fcf_margin": (0.10, 0.20),
        "pe": (20, 12), "ev_ebitda": (13, 8), "pb": (3.5, 1.8), "peg": (1.5, 0.9),
        "fcf_yield": (0.045, 0.08), "earnings_yield": (0.05, 0.09), "dividend_yield": (0.015, 0.035),
    },
    "INDIA": {
        "roe": (0.15, 0.25), "roic": (0.13, 0.22), "roce": (0.13, 0.22),
        "gross_margin": (0.25, 0.45), "operating_margin": (0.13, 0.24), "net_margin": (0.09, 0.18),
        "debt_to_equity": (0.8, 0.35), "interest_coverage": (5, 11), "net_debt_to_ebitda": (2.5, 1.0),
        "current_ratio": (1.3, 2.0),
        "revenue_cagr": (0.11, 0.20), "eps_cagr": (0.12, 0.22), "fcf_margin": (0.08, 0.16),
        "pe": (24, 15), "ev_ebitda": (15, 9), "pb": (4.0, 2.0), "peg": (1.5, 0.9),
        "fcf_yield": (0.05, 0.09), "earnings_yield": (0.045, 0.07), "dividend_yield": (0.012, 0.03),
    },
    "GCC": {
        "roe": (0.13, 0.22), "roic": (0.11, 0.18), "roce": (0.11, 0.18),
        "gross_margin": (0.25, 0.45), "operating_margin": (0.15, 0.28), "net_margin": (0.12, 0.24),
        "debt_to_equity": (0.8, 0.35), "interest_coverage": (5, 12), "net_debt_to_ebitda": (2.5, 1.0),
        "current_ratio": (1.2, 1.8),
        "revenue_cagr": (0.07, 0.15), "eps_cagr": (0.08, 0.16), "fcf_margin": (0.10, 0.20),
        "pe": (16, 10), "ev_ebitda": (11, 7), "pb": (2.0, 1.2), "peg": (1.3, 0.8),
        "fcf_yield": (0.06, 0.10), "earnings_yield": (0.06, 0.10), "dividend_yield": (0.03, 0.06),
    },
    "AU": {
        "roe": (0.14, 0.22), "roic": (0.11, 0.18), "roce": (0.11, 0.18),
        "gross_margin": (0.28, 0.50), "operating_margin": (0.13, 0.24), "net_margin": (0.09, 0.18),
        "debt_to_equity": (1.0, 0.4), "interest_coverage": (5, 12), "net_debt_to_ebitda": (3.0, 1.0),
        "current_ratio": (1.2, 1.8),
        "revenue_cagr": (0.07, 0.14), "eps_cagr": (0.09, 0.17), "fcf_margin": (0.10, 0.20),
        "pe": (19, 12), "ev_ebitda": (12, 8), "pb": (2.5, 1.4), "peg": (1.4, 0.9),
        "fcf_yield": (0.05, 0.09), "earnings_yield": (0.05, 0.08), "dividend_yield": (0.035, 0.06),
    },
}
# Regions that reuse a close proxy until dedicated calibration is added.
_ALIASES = {"EUROPE": "US", "UK": "US", "CANADA": "US", "JAPAN": "US",
            "SINGAPORE": "GCC", "HONGKONG": "GCC"}

# Map our MarketRegion enum values → profile keys.
REGION_TO_PROFILE = {"psx": "PK", "us": "US", "india": "INDIA", "gcc": "GCC", "australia": "AU"}


def country_profile(region: str | None) -> dict[str, tuple[float, float]]:
    key = REGION_TO_PROFILE.get((region or "").lower(), "DEFAULT")
    key = _ALIASES.get(key, key)
    return COUNTRY_PROFILES.get(key, _DEFAULT)


# ── Sector adjustments ───────────────────────────────────────────────────────
# Multipliers applied to a metric's (good, great) band for a sector, plus metrics
# that don't apply (e.g. D/E for banks). Keyword-matched against sector/industry.
FINANCIAL_KEYWORDS = ("bank", "insurance", "financ", "modaraba", "invest", "securities", "reit")

SECTOR_ADJUSTMENTS: list[tuple[tuple[str, ...], dict]] = [
    (FINANCIAL_KEYWORDS, {  # leverage ratios not comparable to industrials
        "skip": {"debt_to_equity", "interest_coverage", "net_debt_to_ebitda",
                 "gross_margin", "fcf_margin", "ev_ebitda"},
    }),
    (("utilit", "power"), {"mult": {"debt_to_equity": 1.8, "interest_coverage": 0.6}}),
    (("cement", "steel", "engineering", "auto", "refiner", "chemical"),
     {"mult": {"debt_to_equity": 1.4, "net_margin": 0.8, "operating_margin": 0.85}}),
    (("technology", "software", "it services"),
     {"mult": {"debt_to_equity": 0.6, "net_margin": 1.2, "gross_margin": 1.2}}),
    (("oil & gas", "oil and gas", "exploration", "e&p"),
     {"mult": {"debt_to_equity": 1.3}}),
]


def sector_adjust(band: tuple[float, float], metric: str, sector: str | None,
                  industry: str | None) -> tuple[float, float] | None:
    """Apply sector rules to a band. Returns None if the metric doesn't apply."""
    hay = f"{sector or ''} {industry or ''}".lower()
    good, great = band
    for keys, rule in SECTOR_ADJUSTMENTS:
        if any(k in hay for k in keys):
            if metric in rule.get("skip", set()):
                return None
            m = rule.get("mult", {}).get(metric)
            if m is not None:
                good, great = good * m, great * m
    return (good, great)
