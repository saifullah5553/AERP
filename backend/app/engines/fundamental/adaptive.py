"""Adaptive fundamental scoring - Pakistan baseline, adjusted by country and sector.

Five categories out of 145.5:

    Growth            18     4 metrics  x weight 90
    Stability         47.5  12 metrics  x weight 79.1667
    Valuation         34     8 metrics  x weight 85
    Working capital   21     5 metrics  x weight 84
    Cash flow         25     5 metrics  x weight 100   (4 cash metrics + Piotroski)

A metric contributes ``score * weight / 100``. The per-metric weights are not stated in the
specification but are forced by it: equal weights within a category are the only assignment
that reproduces the stated maxima.

SCORING IS PRO-RATA, not three-step GOOD/AVERAGE/BAD. The thresholds still set the shape -
BAD anchors 1, AVERAGE anchors 3, GOOD anchors 5 - but a value between two anchors is
interpolated, so 14.9% revenue growth scores 4.98 and 5.1% scores 3.02 instead of both
collapsing to 3. Banding threw away most of the information in each number and let the total
jump on rounding noise: a company a basis point below a threshold lost a whole weighted point
to one a basis point above.

N/A IS THE POINT OF THIS ENGINE. A metric with no economic meaning for a business model is
excluded from the applicable maximum rather than scored 1 - a bank is not a failing
manufacturer because it holds no inventory. The final score is
``earned / applicable_max * 145.5``.

WHAT THIS ENGINE CANNOT DO, stated rather than faked. The specification asks for banking
metrics (NIM, CET1, NPL, CASA, provision coverage), insurance metrics (combined, loss and
expense ratios, solvency) and REIT metrics (FFO, AFFO, NAV, occupancy). None of those line
items exist in our quarterly-TTM store, which carries income, balance sheet and cash flow
only. For those models this engine does the half it can - it marks the industrial metrics
N/A and renormalises - and reports the missing half through ``model_note`` instead of
inventing a proxy and calling it a capital ratio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GOOD, AVERAGE, BAD = 5.0, 3.0, 1.0

CATEGORY_MAX = {
    "growth": 18.0,
    "stability": 47.5,
    "valuation": 34.0,
    "working_capital": 21.0,
    "cash_flow": 25.0,
}
TOTAL_MAX = 145.5

CATEGORY_WEIGHT = {
    "growth": 90.0,
    "stability": 47.5 / 12 / 5 * 100,   # 79.1667
    "valuation": 85.0,
    "working_capital": 84.0,
    "cash_flow": 100.0,
}

CATEGORY_LABEL = {
    "growth": "Growth",
    "stability": "Stability",
    "valuation": "Valuation",
    "working_capital": "Working Capital",
    "cash_flow": "Cash Flow / Business Model",
}


@dataclass(frozen=True)
class Country:
    """Local norms. Pakistan is the baseline and is never adjusted; every other entry carries
    the economic reason for departing from it, because a threshold moved without a
    justification is a preference rather than an analysis."""

    name: str
    risk_free: float
    statutory_tax: float
    pe_good: float
    pe_avg: float
    pb_good: float
    ps_good: float
    ps_avg: float
    div_good: float
    growth_good: float
    growth_avg: float
    ev_ebitda_good: float
    roe_good: float
    why: str


COUNTRIES: dict[str, Country] = {
    "psx": Country(
        "Pakistan", 0.115, 0.29, 10, 15, 1.5, 1.5, 3.0, 0.04, 0.15, 0.05, 10, 0.20,
        "baseline"),
    "us": Country(
        "United States", 0.043, 0.21, 20, 28, 3.0, 2.5, 5.0, 0.02, 0.08, 0.03, 14, 0.15,
        "P/E 10->20: a 4.3% risk-free rate against 11.5% supports roughly double the "
        "multiple. Growth 15%->8%: mature industries in a large economy compound slower. "
        "Dividend 4%->2%: US payout runs largely through buybacks."),
    "australia": Country(
        "Australia", 0.042, 0.30, 18, 25, 2.2, 2.0, 4.0, 0.035, 0.08, 0.03, 12, 0.13,
        "Developed-market rates, and a franking-credit culture that keeps yields high "
        "relative to other developed markets."),
    "india": Country(
        "India", 0.068, 0.25, 22, 32, 3.0, 3.0, 6.0, 0.015, 0.14, 0.06, 15, 0.16,
        "P/E 10->22 despite a 6.8% risk-free rate: sustained double-digit earnings growth is "
        "capitalised by domestic flows. Dividend 4%->1.5%: Indian companies retain."),
    "gcc": Country(
        "Saudi (Tadawul)", 0.050, 0.20, 16, 22, 2.0, 2.5, 4.5, 0.035, 0.10, 0.04, 12, 0.14,
        "Moderate rates, a 20% zakat/tax regime, and government-linked payout policy."),
    "dfm": Country(
        "Dubai (DFM)", 0.045, 0.09, 14, 20, 1.8, 2.5, 4.5, 0.045, 0.10, 0.04, 11, 0.14,
        "9% corporate tax and a high-payout market; rates track the dollar peg."),
}

DEFAULT_COUNTRY = COUNTRIES["psx"]

BANK = "bank"
INSURER = "insurer"
REIT = "reit"
UTILITY = "utility"
COMMODITY = "commodity"
TECH = "tech"
GENERAL = "general"

_MODEL_KEYWORDS: list[tuple[str, str]] = [
    (BANK, "bank"),
    (INSURER, "insurance"), (INSURER, "insurer"), (INSURER, "takaful"),
    (REIT, "reit"), (REIT, "real estate investment"),
    (UTILITY, "utilit"), (UTILITY, "power generation"), (UTILITY, "electricity"),
    (UTILITY, "water"), (UTILITY, "gas distribution"),
    (COMMODITY, "oil"), (COMMODITY, "gas exploration"), (COMMODITY, "mining"),
    (COMMODITY, "metals"), (COMMODITY, "energy"), (COMMODITY, "basic materials"),
    (TECH, "technolog"), (TECH, "software"), (TECH, "semiconduct"),
]

INAPPLICABLE: dict[str, set[str]] = {
    BANK: {
        # A bank funds itself with deposits: interest expense is its cost of goods, not a
        # financing burden, and balance-sheet leverage is the business, not a risk to punish.
        "interest_coverage", "debt_to_equity", "current_ratio", "total_debt",
        "fixed_asset_turnover",
        # Banks do not report an operating profit line, and the specification is explicit that
        # generic margin thresholds must not be applied to them. Marked N/A rather than left
        # to read as missing data, because the distinction is the whole point of the flag.
        "op_cagr", "operating_margin",
        "inventory_turnover", "dso", "dio", "dpo", "ccc",
        # Corporate FCF is not meaningful: CFO swings with deposit flows, not performance.
        "fcf_per_share", "fcf_margin", "fcf_to_cfo", "croic",
        "ev_ebitda",   # enterprise value is meaningless where debt IS the raw material
    },
    INSURER: {
        "interest_coverage", "current_ratio", "inventory_turnover", "dio", "ccc",
        "fixed_asset_turnover", "ev_ebitda", "croic",
    },
    REIT: {"inventory_turnover", "dio", "ccc", "dso", "dpo", "fixed_asset_turnover"},
    UTILITY: {"inventory_turnover", "dio"},
    TECH: {"inventory_turnover", "dio"},
    COMMODITY: set(),
    GENERAL: set(),
}

MODEL_NOTE = {
    BANK: ("Bank: industrial metrics marked N/A and their weight redistributed. NIM, CET1, "
           "NPL, provision coverage, CASA and loan/deposit are NOT scored - those line items "
           "are absent from our statement store, so the banking framework is half applied."),
    INSURER: ("Insurer: combined, loss and expense ratios and solvency are absent from our "
              "statement store; only the generic metrics that stay meaningful are scored."),
    REIT: ("REIT: FFO, AFFO, NAV and occupancy are absent from our statement store, and "
           "depreciation makes conventional EPS understate the business."),
    UTILITY: "Utility: inventory metrics N/A; regulated returns make stability dominate.",
    TECH: "Technology: inventory metrics N/A; valuation thresholds widened for growth.",
    COMMODITY: "Commodity: earnings are cycle-driven; peak margins are not structural.",
    GENERAL: "",
}


def classify_model(sector: str | None, industry: str | None = None,
                   balance: dict | None = None, income: dict | None = None) -> str:
    """Business model, from the label where it is specific and from the BALANCE SHEET where
    it is not.

    Labels alone cannot do this. 1,465 rows in our universe carry the sector "Financial
    Services" and nothing else - JPMorgan, an asset manager, an exchange and a fintech all
    look identical. Classifying them all as banks would apply the bank N/A set to MCX, which
    is an exchange, and the valuation engine already learned that lesson the expensive way
    (MCX valued at 398 against a price of 2,766 for the same confusion).

    So a generic financial label is resolved against the statements: a deposit-funded bank
    carries leverage no operating company does, holds no inventory, and pays out a large
    share of revenue as interest. Fee financials - exchanges, asset managers, index providers
    - fail that test on leverage and stay general, which is the correct answer for them.
    """
    text = f"{sector or ''} {industry or ''}".lower()

    from app.engines.valuation.multi import _FEE_FINANCIAL
    if any(k in text for k in _FEE_FINANCIAL):
        return GENERAL          # one definition of "not a balance-sheet business", not two

    for model, kw in _MODEL_KEYWORDS:
        if kw in text:
            return model

    generic_financial = "financial" in text
    if generic_financial and balance and income:
        assets = _f(balance.get("total_assets"))
        equity = _f(balance.get("total_equity"))
        inventory = _f(balance.get("inventory"))
        interest = _f(income.get("interest_expense"))
        revenue = _f(income.get("revenue"))
        leverage = (assets / equity) if (assets and equity and equity > 0) else None
        int_share = (interest / revenue) if (interest and revenue and revenue > 0) else None
        if (leverage is not None and leverage >= 6.0
                and not inventory
                and (int_share is None or int_share >= 0.10)):
            return BANK
    return GENERAL


# ---------------------------------------------------------------- helpers

def _f(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _series(rows: list[dict], key: str) -> list[float | None]:
    """Newest first, as stored."""
    return [_f(r.get(key)) for r in rows]


def _avg(vals: list[float | None], n: int) -> float | None:
    clean = [v for v in vals[:n] if v is not None]
    return sum(clean) / len(clean) if clean else None


def _at(vals: list[float | None], idx: int) -> float | None:
    return vals[idx] if 0 <= idx < len(vals) else None


def _cagr(vals: list[float | None], quarters: int) -> float | None:
    """CAGR from the TTM `quarters` periods ago to the current TTM.

    Every stored row is already a full trailing year, so twelve rows back is three years back.
    Refuses on a non-positive base: a company that was loss-making has no meaningful profit
    CAGR, and (end/begin)^(1/n) across a sign change is arithmetic noise, not growth.
    """
    end, begin = _at(vals, 0), _at(vals, quarters)
    if end is None or begin is None or begin <= 0 or end <= 0:
        return None
    return (end / begin) ** (4.0 / quarters) - 1.0


def prorata(value: float | None, bad: float, avg: float, good: float) -> float | None:
    """Continuous 1..5 by linear interpolation between the band anchors.

    `bad`, `avg` and `good` are the values at which the metric scores 1, 3 and 5. They may run
    in either direction, so the same function serves "higher is better" (growth) and "lower is
    better" (P/E) without a flag to get the wrong way round.
    """
    if value is None:
        return None
    if good > bad:                       # higher is better
        if value <= bad:
            return BAD
        if value >= good:
            return GOOD
        if value <= avg:
            return BAD + (value - bad) / (avg - bad) * (AVERAGE - BAD)
        return AVERAGE + (value - avg) / (good - avg) * (GOOD - AVERAGE)
    # lower is better
    if value >= bad:
        return BAD
    if value <= good:
        return GOOD
    if value >= avg:
        return BAD + (bad - value) / (bad - avg) * (AVERAGE - BAD)
    return AVERAGE + (avg - value) / (avg - good) * (GOOD - AVERAGE)


def prorata_change(now: float | None, then: float | None, lower_is_better: bool = False,
                   full: float = 0.25) -> float | None:
    """Score a 3-year average against a 5-year average, pro-rata on the relative change.

    The specification scores these comparisons as a binary better/worse. Pro-rata keeps the
    direction but grades the size: `full` is the relative improvement that earns a 5, so a
    company that lifted cash flow 30% scores above one that lifted it 1%, and a rounding-level
    difference sits near the neutral 3 instead of being called GOOD.
    """
    if now is None or then is None or then == 0:
        return None
    change = (now - then) / abs(then)
    if lower_is_better:
        change = -change
    if change >= full:
        return GOOD
    if change <= -full:
        return BAD
    return AVERAGE + (change / full) * (GOOD - AVERAGE)


@dataclass
class Metric:
    key: str
    category: str
    label: str
    value: float | None = None
    avg3: float | None = None
    avg5: float | None = None
    score: float | None = None      # None means not scored - excluded from the maximum
    benchmark: str = ""
    note: str = ""
    # WHY there is no score, which the maximum depends on. `na_model` means the metric has no
    # economic meaning for this business model and the specification says to redistribute its
    # weight. Anything else with score None is simply MISSING DATA, and those two must not be
    # treated alike: dropping a missing metric from the maximum quietly rewards a company for
    # having sparse statements, which is the opposite of what a data-quality gate should do.
    na_model: bool = False

    @property
    def weight(self) -> float:
        return CATEGORY_WEIGHT[self.category]

    @property
    def weighted(self) -> float | None:
        return None if self.score is None else self.score * self.weight / 100.0

    @property
    def max_weighted(self) -> float:
        return GOOD * self.weight / 100.0


@dataclass
class AdaptiveResult:
    score: float | None = None            # normalised to the 145.5 scale
    percent: float | None = None          # 0-100
    rating: str = "Unrated"
    country: str = ""
    country_why: str = ""
    model: str = GENERAL
    model_note: str = ""
    applicable_max: float = 0.0
    raw_earned: float = 0.0
    categories: dict[str, dict] = field(default_factory=dict)
    metrics: list[Metric] = field(default_factory=list)
    piotroski: int | None = None
    accounting_risk: str = "LOW"
    accounting_flags: list[str] = field(default_factory=list)
    matrix: dict[str, str] = field(default_factory=dict)
    classification: str = ""
    trend: str = ""
    coverage: float = 0.0

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "percent": self.percent,
            "rating": self.rating,
            "country": self.country,
            "model": self.model,
            "model_note": self.model_note,
            "applicable_max": round(self.applicable_max, 2),
            "raw_earned": round(self.raw_earned, 2),
            "categories": self.categories,
            "piotroski": self.piotroski,
            "accounting_risk": self.accounting_risk,
            "accounting_flags": self.accounting_flags,
            "matrix": self.matrix,
            "classification": self.classification,
            "trend": self.trend,
            "coverage": self.coverage,
            "metrics": [
                {
                    "key": m.key, "category": m.category, "label": m.label,
                    "value": m.value, "avg3": m.avg3, "avg5": m.avg5,
                    "score": None if m.score is None else round(m.score, 2),
                    "weighted": None if m.weighted is None else round(m.weighted, 3),
                    "benchmark": m.benchmark, "note": m.note,
                }
                for m in self.metrics
            ],
        }


RATING_BANDS = [
    (85.0, "EXCEPTIONAL"),
    (75.0, "VERY STRONG"),
    (65.0, "STRONG"),
    (55.0, "AVERAGE / ACCEPTABLE"),
    (45.0, "WEAK"),
]


def rating_for(percent: float | None) -> str:
    if percent is None:
        return "Unrated"
    for floor, label in RATING_BANDS:
        if percent >= floor:
            return label
    return "POOR"


def _tier(percent: float | None, bands=(75.0, 62.0, 50.0)) -> str:
    if percent is None:
        return "Unrated"
    hi, mid, lo = bands
    if percent >= hi:
        return "Exceptional"
    if percent >= mid:
        return "Strong"
    if percent >= lo:
        return "Average"
    return "Weak"


def _valuation_tier(percent: float | None) -> str:
    if percent is None:
        return "Unrated"
    if percent >= 80:
        return "Very Attractive"
    if percent >= 65:
        return "Attractive"
    if percent >= 50:
        return "Fair"
    if percent >= 35:
        return "Expensive"
    return "Very Expensive"
