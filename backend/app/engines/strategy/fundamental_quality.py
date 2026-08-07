"""Fundamental Quality Score — 0-100, from 20 trailing-twelve-month observations.

Six categories, weighted as specified:

    A  Growth & growth quality            20
    B  Profitability & margins            20
    C  Cash flow & earnings quality       25
    D  Balance sheet & debt               15
    E  Liquidity & cash reserves          10
    F  Working capital & capital efficiency 10

Cash flow carries the largest single weight, which is the point of the design: reported profit
is an opinion until it arrives as cash, and the category that checks whether it did should
outweigh the one that reports it.

EVERY ONE OF THE 20 TTM PERIODS IS SCORED SEPARATELY, each on only the statements that existed
at that point - never on later ones. The primary output is the time series, not the latest
number; the latest number is simply its last point.

Four rules run through the whole engine, and they are what separate it from a checklist:

MAGNITUDE, NOT PASS/FAIL. Every metric is scored on an interpolated curve, so 10.1% beats
10.0% and 25% beats 20%. No band is flat inside itself. A threshold model cannot tell a
company compounding at 25% from one limping at 11%, and both were previously "passes".

TREND COUNTS SEPARATELY FROM LEVEL. Two companies at 15% ROIC are not the same company if one
climbed from 10% and the other fell from 25%. Each category scores its current level AND the
direction of travel across the 20 periods.

OUTLIERS ARE CAPPED, NOT EXTRAPOLATED. 100x interest cover is excellent; it is not twenty
times as excellent as 5x. Every curve flattens at its top knot, so one freak ratio cannot
carry a company that is otherwise mediocre.

PURELY QUANTITATIVE. Only the statements decide the score. No country, inflation or interest
-rate assumption enters it, so the same numbers earn the same marks in every market and no
score moves because a macro constant was revised.

WHAT CANNOT BE COMPUTED IS NOT GUESSED. A missing input drops out and its category renormalises
over what remains, rather than being filled with a default that would read as a real
measurement. A category with nothing measurable drops its budget instead of scoring zero.

The input is ALREADY TTM - each row is a full trailing twelve months. Nothing here re-rolls or
re-sums it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── category budgets ────────────────────────────────────────────────────────────────────
# A: growth. B: profitability AND the returns earned on the accounting base. C: cash flow and
# earnings quality, the heaviest single category. D: leverage and its servicing. E: liquidity,
# which used to be two ratios buried in D and is now judged on its own terms. F: how efficiently
# capital and working capital are turned.
#
# ROIC is scored ONCE, in F. The specification lists it under both B and F; scoring it twice
# would let one characteristic carry
# a fifth of the total through the back door, which is the
# double-counting the spec itself warns against.
CATEGORY_POINTS: dict[str, float] = {
    "growth": 20.0,
    "profitability": 20.0,
    "cash_flow": 25.0,
    "balance_sheet": 15.0,
    "liquidity": 10.0,
    "working_capital": 10.0,
}
MAX_PERIODS = 20

# Sectors whose economics make industrial metrics meaningless. A bank's "debt" is its funding
# and its current ratio says nothing, so those checks are dropped rather than scored as though
# the business were failing them - which is what marks every bank down in a naive model.
FINANCIAL_SECTORS = {
    "financials", "financial services", "banks", "commercial banks", "insurance",
    "inv. banks / inv. cos. / securities cos.", "investment banks", "real estate",
}

# No country adjustment, by decision. The score is a QUANTITATIVE read of the statements and
# nothing else: the same revenue growth, the same ROIC and the same interest cover earn the
# same marks in Karachi as in New York. An earlier build deflated growth by a per-market
# inflation figure and scored coverage against a per-market floor - defensible in theory, but
# it meant a single assumed constant silently moved every score in a market, and the number
# stopped being a reading of the accounts.
#
# The consequence is stated rather than hidden: where inflation is high, some of the reported
# growth is inflation, and this score does not separate the two.
COVERAGE_FLOOR = 3.0


def _f(v: Any) -> float | None:
    """A float, or None. Bools are not numbers here however much Python disagrees."""
    if v is None or isinstance(v, bool):
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return None if out != out or out in (float("inf"), float("-inf")) else out


def curve(value: float | None, knots: list[tuple[float, float]]) -> float | None:
    """0..1 for `value`, linearly interpolated between (threshold, fraction) knots.

    The knots carry the economics; the interpolation is what stops a band being flat inside
    itself. Outside the ends the curve FLATTENS rather than continuing - that is the outlier
    cap, and it is the reason a 300% one-off growth spike cannot outscore a decade of 25%.

    Knots must be ascending by threshold. Fractions may descend, which is how a lower-is-better
    metric is expressed - no separate code path, just a downward curve.
    """
    if value is None or not knots:
        return None
    if value <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:], strict=False):
        if value <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * ((value - x0) / (x1 - x0))
    return knots[-1][1]


def _series(rows: list[dict], key: str) -> list[float | None]:
    """`key` across the periods, OLDEST first, gaps preserved as None.

    Order matters more than it looks: the stored statements are newest-first, and a trend read
    off them unreversed reports every improving company as deteriorating.
    """
    return [_f(r.get(key)) for r in reversed(rows[:MAX_PERIODS])]


def _clean(vals: list[float | None]) -> list[float]:
    return [v for v in vals if v is not None]


def _latest(vals: list[float | None]) -> float | None:
    for v in reversed(vals):
        if v is not None:
            return v
    return None


def periods_per_year(rows: list[dict]) -> int:
    """How many stored rows make up a year, read off the dates rather than assumed.

    The scraped TTM store is quarterly-spaced, so a year is four rows back. The fallback
    statements are ANNUAL, where a year is one row back. Assuming four either way compares an
    annual filer with itself four YEARS earlier and calls the answer year-on-year growth.
    """
    dates = [str(r.get("fiscal_date") or "")[:10] for r in rows[:MAX_PERIODS]]
    dates = [d for d in dates if len(d) == 10]
    if len(dates) < 2:
        return 1
    try:
        gaps = []
        for newer, older in zip(dates, dates[1:], strict=False):
            y = int(newer[:4]) * 12 + int(newer[5:7])
            o = int(older[:4]) * 12 + int(older[5:7])
            if y - o > 0:
                gaps.append(y - o)
    except ValueError:
        return 4
    if not gaps:
        return 4
    median_months = sorted(gaps)[len(gaps) // 2]
    return 1 if median_months >= 7 else 4


def _yoy(vals: list[float | None], per_year: int = 4) -> float | None:
    """Growth over one year, measured in however many rows a year takes."""
    clean = _clean(vals)
    if len(clean) < per_year + 1:
        return None
    now, then = clean[-1], clean[-(per_year + 1)]
    if then is None or then == 0:
        return None
    # A swing out of losses has no meaningful percentage; scoring it would reward the loss.
    if then < 0 <= now:
        return None
    return (now - then) / abs(then)


def _cagr(vals: list[float | None], years: int, per_year: int = 4) -> float | None:
    clean = _clean(vals)
    need = years * per_year + 1
    if len(clean) < need:
        return None
    now, then = clean[-1], clean[-need]
    if then is None or then <= 0 or now <= 0:
        return None
    return (now / then) ** (1.0 / years) - 1.0


def trend(vals: list[float | None]) -> float | None:
    """-1..+1: is this metric climbing or sliding across the history?

    The mean of the newest third against the oldest third, scaled by the spread. Compared with
    a first-versus-last reading this survives one freak quarter at either end, which is exactly
    where a two-point trend goes wrong.
    """
    clean = _clean(vals)
    if len(clean) < 6:
        return None
    third = max(2, len(clean) // 3)
    old = sum(clean[:third]) / third
    new = sum(clean[-third:]) / third
    scale = max(abs(old), abs(new))
    if scale == 0:
        return 0.0
    return max(-1.0, min(1.0, (new - old) / scale))


def _blend(level: float | None, direction: float | None, trend_weight: float = 0.25
           ) -> float | None:
    """Fold a trend into a level score. Direction shifts it; level still decides it."""
    if level is None:
        return None
    if direction is None:
        return level
    return max(0.0, min(1.0, level * (1 - trend_weight) + trend_weight * (0.5 + direction / 2)))


@dataclass(slots=True)
class Category:
    points: float
    earned: float
    parts: dict[str, float | None] = field(default_factory=dict)

    @property
    def pct(self) -> float:
        return (self.earned / self.points) if self.points else 0.0


def _weigh(parts: dict[str, tuple[float | None, float]], points: float) -> Category:
    """Weighted mean of the sub-scores that could be computed, scaled to the category budget.

    Renormalising over what exists is the whole point: a company whose interest expense is not
    reported must not be scored as if it had failed interest cover.
    """
    live = {k: (s, w) for k, (s, w) in parts.items() if s is not None}
    total_w = sum(w for _, w in live.values())
    if not total_w:
        # NOTHING in this category could be computed, which is not the same as failing it.
        # Scoring 0 out of the full budget marks a company down for what we cannot see - and
        # with a single quarter of history, growth and every trend are uncomputable, so a
        # newly-scraped company would be handed 0/20 for growth it was never measured on.
        # Dropping the budget to zero renormalises the category away, exactly as a bank's
        # working capital is.
        return Category(points=0.0, earned=0.0,
                        parts={k: None for k in parts})
    earned = (sum(s * w for s, w in live.values()) / total_w * points) if total_w else 0.0
    return Category(points=points, earned=earned,
                    parts={k: (round(s, 4) if s is not None else None)
                           for k, (s, _) in parts.items()})


def _ratio_series(num: list[float | None], den: list[float | None]) -> list[float | None]:
    return [(n / d) if (n is not None and d not in (None, 0)) else None
            for n, d in zip(num, den, strict=False)]


# ── A. Growth & growth quality — 20 ─────────────────────────────────────────────────────
# Real growth, not nominal. Deflating by the market's inflation is what lets a Pakistani and
# an American company be compared without handing one a currency-driven head start.
# Calibrated to the specified table, out of 5:
#   5% -> 2.1   10% -> 3.0   15% -> 3.7   20% -> 4.4   25% -> 5.0
# Note the SHAPE: the steps shrink as growth rises (+0.9, +0.7, +0.7, +0.6). Growth is worth
# most where it is scarce; the difference between 5% and 10% matters more than between 20% and
# 25%, and a straight line would say otherwise. Full marks at 25% and flat above, so a 200%
# one-off cannot outscore a company compounding at 25%.
_GROWTH_KNOTS = [(-0.10, 0.0), (0.0, 0.22), (0.05, 0.42), (0.10, 0.60),
                 (0.15, 0.74), (0.20, 0.88), (0.25, 1.0)]


def _score_growth(m: dict, per_year: int = 4) -> Category:
    rev, ebit = m["revenue"], m["operating_income"]
    parts: dict[str, tuple[float | None, float]] = {
        "revenue_growth": (_blend(curve(_yoy(rev, per_year), _GROWTH_KNOTS),
                                  trend(rev)), 0.24),
        "revenue_cagr_3y": (curve(_cagr(rev, 3, per_year), _GROWTH_KNOTS), 0.12),
        "operating_profit_growth": (
            _blend(curve(_yoy(ebit, per_year), _GROWTH_KNOTS), trend(ebit)), 0.20),
        "net_income_growth": (curve(_yoy(m["net_income"], per_year), _GROWTH_KNOTS), 0.14),
        # Per-share, not headline. Twenty percent more profit on fifteen percent more shares is
        # not twenty percent more for the holder, and only EPS notices the difference.
        "eps_growth": (_blend(curve(_yoy(m["eps"], per_year), _GROWTH_KNOTS),
                              trend(m["eps"])), 0.20),
        "fcf_growth": (curve(_yoy(m["free_cash_flow"], per_year), _GROWTH_KNOTS), 0.10),
    }
    return _weigh(parts, CATEGORY_POINTS["growth"])


# ── B. Profitability & margins — 20 ─────────────────────────────────────────────────────
_MARGIN_KNOTS = [(0.0, 0.05), (0.03, 0.20), (0.06, 0.35), (0.10, 0.55),
                 (0.15, 0.72), (0.20, 0.85), (0.30, 0.95), (0.45, 1.0)]
_GROSS_KNOTS = [(0.05, 0.05), (0.12, 0.20), (0.20, 0.40), (0.30, 0.60),
                (0.40, 0.78), (0.55, 0.92), (0.70, 1.0)]


def _peer_relative(value: float | None, median: float | None) -> float | None:
    """Where this margin sits against its industry, on a curve centred at the median.

    Absolute level still carries the category. This only tilts it, because a company is not
    high quality merely for being the best of a poor sector - and not poor for earning an
    ordinary margin in a structurally thin one.
    """
    if value is None or median is None or median == 0:
        return None
    rel = value / abs(median)
    return curve(rel, [(0.4, 0.05), (0.7, 0.25), (1.0, 0.5), (1.3, 0.72),
                       (1.8, 0.88), (2.5, 1.0)])


def _score_profitability(m: dict, peers: dict | None, financial: bool = False) -> Category:
    peers = peers or {}
    gross = _ratio_series(m["gross_profit"], m["revenue"])
    ebitda_m = _ratio_series(m["ebitda"], m["revenue"])
    op_m = _ratio_series(m["operating_income"], m["revenue"])
    net_m = _ratio_series(m["net_income"], m["revenue"])

    def pair(series: list[float | None], knots: list[tuple[float, float]],
             peer_key: str) -> float | None:
        level = curve(_latest(series), knots)
        level = _blend(level, trend(series))
        rel = _peer_relative(_latest(series), peers.get(peer_key))
        if level is None:
            return rel
        return level if rel is None else level * 0.7 + rel * 0.3

    # Returns on the accounting base belong here with the margins: a margin says what the
    # business keeps of each sale, a return says what it earns on what was put in, and judging
    # profitability on the first alone flatters an asset-heavy company that never earns its
    # capital back. ROIC is deliberately NOT here - it is scored once, in working capital.
    roe = _ratio_series(m["net_income"], m["total_equity"])
    roa = _ratio_series(m["net_income"], m["total_assets"])

    # DuPont: leverage inflates ROE without improving the business. A 25% ROE carried by
    # assets/equity of 6x is not the same achievement as one at 1.5x, so the score is damped by
    # how much of it is borrowed rather than earned.
    lev = _ratio_series(m["total_assets"], m["total_equity"])
    lev_now = _latest(lev)
    roe_level = _blend(curve(_latest(roe), _RETURN_KNOTS), trend(roe))
    if roe_level is not None and lev_now is not None and not financial:
        damp = curve(lev_now, [(1.5, 1.0), (2.5, 0.95), (4.0, 0.82), (6.0, 0.68), (9.0, 0.5)])
        roe_level *= damp if damp is not None else 1.0

    # ROIC sits HERE, with the other return measures, and nowhere else. It is the return a
    # business earns on the capital actually put into it - the measure compared against the
    # cost of that capital to decide whether value is being created at all - which makes it a
    # profitability question, not an operational-efficiency one. Asset turnover and the cash
    # cycle are the efficiency drivers, and they stay in category F.
    #
    # It carries the largest weight in the category for the same reason: margins say what the
    # business keeps per sale, ROIC says whether the sale was worth financing.
    roic = None if financial else _blend(curve(_latest(_roic_series(m)), _RETURN_KNOTS),
                                         trend(_roic_series(m)))

    parts: dict[str, tuple[float | None, float]] = {
        "gross_margin": (pair(gross, _GROSS_KNOTS, "gross_margin"), 0.12),
        "ebitda_margin": (pair(ebitda_m, _MARGIN_KNOTS, "ebitda_margin"), 0.14),
        "operating_margin": (pair(op_m, _MARGIN_KNOTS, "operating_margin"), 0.16),
        "net_margin": (pair(net_m, _MARGIN_KNOTS, "net_margin"), 0.14),
        "roic": (roic, 0.24),
        "roe": (roe_level, 0.12),
        "roa": (_blend(curve(_latest(roa), _ROA_KNOTS), trend(roa)), 0.08),
    }
    return _weigh(parts, CATEGORY_POINTS["profitability"])


# ── C. Capital efficiency — 20 ──────────────────────────────────────────────────────────
# Calibrated to the specified table, out of 8:
#   6% -> 2.0   10% -> 3.2   15% -> 4.8   20% -> 6.5   25% -> 7.5   30% -> 8.0
# This curve ACCELERATES through the middle and then flattens: the step from 15% to 20% is the
# largest (+1.7), because that is where a business crosses from covering its cost of capital to
# genuinely compounding. Above 25% the gains taper - 30% is exceptional, not twice as good
# as 15%.
_RETURN_KNOTS = [(0.0, 0.03), (0.06, 0.25), (0.10, 0.40), (0.15, 0.60),
                 (0.20, 0.8125), (0.25, 0.9375), (0.30, 1.0)]
_ROA_KNOTS = [(0.0, 0.05), (0.02, 0.20), (0.05, 0.45), (0.08, 0.65),
              (0.12, 0.85), (0.18, 1.0)]
_TURNOVER_KNOTS = [(0.15, 0.10), (0.35, 0.30), (0.60, 0.55), (0.90, 0.75),
                   (1.30, 0.90), (2.00, 1.0)]


def _roic_series(m: dict) -> list[float | None]:
    """ROIC = NOPAT / (debt + equity - cash), period by period.

    Split out of the old capital-efficiency category so it can be scored in exactly one place.
    Meaningless for a bank, where debt IS the raw material, so the caller drops it there rather
    than scoring it as catastrophic.
    """
    tax_rate = []
    for pre, tax in zip(m["income_before_tax"], m["income_tax_expense"], strict=False):
        tax_rate.append(max(0.0, min(0.45, tax / pre)) if (pre and pre > 0 and tax) else 0.25)
    nopat = [(e * (1 - t)) if e is not None else None
             for e, t in zip(m["operating_income"], tax_rate, strict=False)]
    invested = []
    for debt, eq, cash in zip(m["total_debt"], m["total_equity"], m["cash"], strict=False):
        if eq is None:
            invested.append(None)
            continue
        base = (debt or 0.0) + eq - (cash or 0.0)
        invested.append(base if base > 0 else None)
    return _ratio_series(nopat, invested)


# ── D. Cash flow & earnings quality — 20 ────────────────────────────────────────────────
_CONVERSION_KNOTS = [(0.0, 0.02), (0.40, 0.20), (0.70, 0.45), (0.90, 0.65),
                     (1.05, 0.82), (1.30, 0.95), (1.80, 1.0)]
_FCF_MARGIN_KNOTS = [(-0.05, 0.0), (0.0, 0.12), (0.03, 0.30), (0.07, 0.52),
                     (0.12, 0.72), (0.18, 0.88), (0.28, 1.0)]


def _score_cash_flow(m: dict, per_year: int = 4) -> tuple[Category, list[str]]:
    """Cash, and whether the reported profit is backed by any of it."""
    cfo, ni, rev = m["operating_cash_flow"], m["net_income"], m["revenue"]
    fcf = m["free_cash_flow"]
    if not _clean(fcf):
        fcf = [(c - abs(x)) if (c is not None and x is not None) else None
               for c, x in zip(cfo, m["capital_expenditure"], strict=False)]

    cfo_ni = _ratio_series(cfo, ni)
    fcf_ni = _ratio_series(fcf, ni)
    cfo_ebitda = _ratio_series(cfo, m["ebitda"])
    fcf_margin = _ratio_series(fcf, rev)
    cfo_margin = _ratio_series(cfo, rev)

    # Consistency: profit converted to cash in most periods beats one spectacular year, which
    # is usually a working-capital release rather than an earning business.
    positives = list(_clean(fcf))
    consistency = (sum(1 for v in positives if v > 0) / len(positives)) if positives else None

    parts: dict[str, tuple[float | None, float]] = {
        "cfo_margin": (_blend(curve(_latest(cfo_margin), _FCF_MARGIN_KNOTS),
                              trend(cfo_margin)), 0.18),
        "cfo_to_net_income": (curve(_latest(cfo_ni), _CONVERSION_KNOTS), 0.22),
        "fcf_margin": (_blend(curve(_latest(fcf_margin), _FCF_MARGIN_KNOTS),
                              trend(fcf_margin)), 0.22),
        "fcf_to_net_income": (curve(_latest(fcf_ni), _CONVERSION_KNOTS), 0.14),
        "cfo_to_ebitda": (curve(_latest(cfo_ebitda), _CONVERSION_KNOTS), 0.10),
        "fcf_consistency": (consistency, 0.14),
    }
    cat = _weigh(parts, CATEGORY_POINTS["cash_flow"])

    # ── earnings-quality penalties, scaled by persistence ──────────────────────────────
    # One soft period is noise. Five in a row is a pattern, and it is the pattern that precedes
    # a restatement - so the penalty grows with how long it has run, not with how bad a single
    # period looked.
    flags: list[str] = []
    penalty = 0.0

    live_cfo_ni = _clean(cfo_ni)
    if len(live_cfo_ni) >= 4:
        share = sum(1 for v in live_cfo_ni if v < 0.8) / len(live_cfo_ni)
        if share >= 0.4:
            penalty += min(0.22, share * 0.22)
            flags.append("earnings persistently not backed by operating cash")

    # Profit up while cash goes the other way - the classic accrual divergence.
    ni_t, cfo_t = trend(ni), trend(cfo)
    if ni_t is not None and cfo_t is not None and ni_t > 0.10 and cfo_t < -0.10:
        penalty += min(0.15, (ni_t - cfo_t) * 0.15)
        flags.append("net income rising while operating cash flow falls")

    # Receivables or inventory outrunning revenue: sales booked faster than they are collected,
    # or goods piling up. Judged against REVENUE growth, since both should scale with it.
    rev_g = _yoy(rev, per_year)
    for key, label in (("receivables", "receivables"), ("inventory", "inventory")):
        g = _yoy(m[key], per_year)
        if g is not None and rev_g is not None and g > rev_g + 0.20:
            penalty += min(0.10, (g - rev_g) * 0.20)
            flags.append(f"{label} growing well ahead of revenue")

    fcf_clean = _clean(fcf)
    if fcf_clean and sum(1 for v in fcf_clean if v < 0) / len(fcf_clean) >= 0.6:
        penalty += 0.12
        flags.append("free cash flow negative in most periods")

    if penalty:
        cat = Category(points=cat.points, earned=cat.earned * (1 - min(0.5, penalty)),
                       parts={**cat.parts, "earnings_quality_penalty": round(-penalty, 4)})
    return cat, flags


# ── E. Balance sheet & solvency — 15 ────────────────────────────────────────────────────
_NET_DEBT_EBITDA_KNOTS = [(-1.0, 1.0), (0.0, 0.95), (1.0, 0.82), (2.0, 0.66),
                          (3.0, 0.45), (4.5, 0.22), (6.0, 0.05)]
_DE_KNOTS = [(0.0, 0.95), (0.3, 0.90), (0.6, 0.78), (1.0, 0.62),
             (1.6, 0.40), (2.5, 0.18), (4.0, 0.03)]
_CURRENT_KNOTS = [(0.6, 0.05), (1.0, 0.30), (1.3, 0.55), (1.7, 0.78),
                  (2.5, 0.92), (4.0, 0.85)]
_QUICK_KNOTS = [(0.3, 0.05), (0.7, 0.30), (1.0, 0.60), (1.4, 0.82), (2.2, 0.95)]
# FCF / total debt. Rating-agency territory: below ~5% the debt is not being repaid out of
# operations, around 20% is comfortable, and above 60% the company could clear its borrowings
# inside two years. Flat at the top - being able to repay three times over is not three times
# safer than being able to repay once.
_FCF_DEBT_KNOTS = [(-0.10, 0.0), (0.0, 0.10), (0.05, 0.28), (0.12, 0.50),
                   (0.20, 0.68), (0.35, 0.85), (0.60, 1.0)]
_DEBT_ASSETS_KNOTS = [(0.0, 0.95), (0.15, 0.85), (0.30, 0.68), (0.45, 0.45),
                      (0.60, 0.22), (0.80, 0.05)]


def _negated(direction: float | None) -> float | None:
    """Flip a trend for a metric where falling is the improvement."""
    return None if direction is None else -direction


def _score_balance_sheet(m: dict, financial: bool) -> Category:
    net_debt = []
    for debt, cash, sti in zip(m["total_debt"], m["cash"], m["short_term_investments"],
                               strict=False):
        net_debt.append(None if debt is None else debt - (cash or 0.0) - (sti or 0.0))
    nd_ebitda = _ratio_series(net_debt, m["ebitda"])
    de = _ratio_series(m["total_debt"], m["total_equity"])
    debt_assets = _ratio_series(m["total_debt"], m["total_assets"])
    # Free cash flow against total debt: the share of borrowings a year's free cash could
    # retire. Reported FCF where the statement gives it, otherwise CFO less capex.
    fcf = [f if f is not None else ((o - abs(c)) if (o is not None and c is not None) else None)
           for f, o, c in zip(m["free_cash_flow"], m["operating_cash_flow"],
                              m["capital_expenditure"], strict=False)]
    fcf_debt = _ratio_series(fcf, m["total_debt"])
    # The current and quick ratios have moved to the liquidity category, where they are scored
    # against cash cover rather than competing with leverage for the same 15 points.

    # One coverage curve for every market: can this company pay its interest out of operating
    # profit, and by how wide a margin.
    floor = COVERAGE_FLOOR
    cover = _ratio_series(m["operating_income"],
                          [abs(v) if v else None for v in m["interest_expense"]])
    cover_knots = [(0.0, 0.0), (1.0, 0.10), (floor, 0.40), (floor * 2, 0.65),
                   (floor * 4, 0.85), (floor * 10, 1.0)]

    parts: dict[str, tuple[float | None, float]] = {
        # Leverage is not a sin. A business funding productive assets at a rate its cash
        # comfortably covers is not worse than one holding no debt at all, so these curves
        # flatten near zero instead of rewarding an empty balance sheet.
        "net_debt_to_ebitda": (
            None if financial else _blend(curve(_latest(nd_ebitda), _NET_DEBT_EBITDA_KNOTS),
                                          _negated(trend(nd_ebitda))), 0.24),
        # Direction is folded into the leverage RATIOS, never measured on the absolute debt
        # figure. A growing company funds a bigger business with a bigger balance sheet; its
        # debt rises in step with its equity and nothing has weakened. Scoring the raw total
        # docked 0.7 points from a company purely for growing at 25% instead of 10%, which is
        # the opposite of what the balance sheet is being asked.
        "debt_to_equity": (_blend(curve(_latest(de), _DE_KNOTS), _negated(trend(de))), 0.18),
        "debt_to_assets": (_blend(curve(_latest(debt_assets), _DEBT_ASSETS_KNOTS),
                                  _negated(trend(debt_assets))), 0.12),
        "interest_coverage": (_blend(curve(_latest(cover), cover_knots), trend(cover)), 0.24),
        # Repayment capacity: how much of the debt one year's free cash flow would retire. The
        # standard credit measure, and the right way to express "profit up, cash flow up, debt
        # down" - it rises when cash generation outpaces borrowing and falls when it does not,
        # WITHOUT punishing a company for funding a larger business with a larger balance
        # sheet. Trending the raw debt total did punish exactly that.
        "fcf_to_debt": (None if financial else _blend(curve(_latest(fcf_debt),
                                                            _FCF_DEBT_KNOTS),
                                                      trend(fcf_debt)), 0.24),
    }
    return _weigh(parts, CATEGORY_POINTS["balance_sheet"])


# ── E. Liquidity & cash reserves — 10 ───────────────────────────────────────────────────
# Its own category now. The current and quick ratios used to sit inside the balance sheet on a
# combined 18% of 15 points - under three points for the entire question of whether the company
# can pay what falls due. Cash against debt and against current liabilities was not asked at all.
_CASH_DEBT_KNOTS = [(0.0, 0.05), (0.10, 0.22), (0.25, 0.42), (0.50, 0.62),
                    (1.00, 0.85), (2.00, 1.0)]
_CASH_CL_KNOTS = [(0.0, 0.05), (0.08, 0.20), (0.20, 0.40), (0.40, 0.62),
                  (0.75, 0.85), (1.50, 1.0)]


def _score_liquidity(m: dict, financial: bool) -> Category:
    """Can this company meet what falls due, and is that getting easier or harder?

    Scored relative to obligations, never on the absolute cash pile: a large balance means
    nothing next to larger debts, and the spec is explicit that size alone must not be
    rewarded.
    """
    cash_total = []
    for cash, sti in zip(m["cash"], m["short_term_investments"], strict=False):
        cash_total.append(None if cash is None else cash + (sti or 0.0))

    cash_debt = [(c / d) if (c is not None and d) else (1.5 if (c and not d) else None)
                 for c, d in zip(cash_total, m["total_debt"], strict=False)]
    cash_cl = _ratio_series(cash_total, m["current_liabilities"])
    current = _ratio_series(m["current_assets"], m["current_liabilities"])
    quick = _ratio_series(
        [(ca - (inv or 0.0)) if ca is not None else None
         for ca, inv in zip(m["current_assets"], m["inventory"], strict=False)],
        m["current_liabilities"])

    # Net cash - holding more cash than total debt - is a genuine step change in resilience,
    # not a point on a continuum, so it earns a flat mark of its own.
    net_cash = None
    c_now, d_now = _latest(cash_total), _latest(m["total_debt"])
    if c_now is not None and d_now is not None:
        net_cash = 1.0 if c_now > d_now else curve(c_now / d_now if d_now else 1.5,
                                                   _CASH_DEBT_KNOTS)

    parts: dict[str, tuple[float | None, float]] = {
        "cash_to_debt": (_blend(curve(_latest(cash_debt), _CASH_DEBT_KNOTS),
                                trend(cash_debt)), 0.30),
        "cash_to_current_liabilities": (_blend(curve(_latest(cash_cl), _CASH_CL_KNOTS),
                                               trend(cash_cl)), 0.24),
        "net_cash_position": (net_cash, 0.16),
        # A bank's current ratio is not a solvency statement; its cash cover still is.
        "current_ratio": (None if financial else _blend(curve(_latest(current),
                                                              _CURRENT_KNOTS),
                                                        trend(current)), 0.18),
        "quick_ratio": (None if financial else curve(_latest(quick), _QUICK_KNOTS), 0.12),
    }
    return _weigh(parts, CATEGORY_POINTS["liquidity"])


# ── F. Working capital & operating efficiency — 5 ───────────────────────────────────────
_CCC_KNOTS = [(-60.0, 1.0), (0.0, 0.92), (30.0, 0.75), (60.0, 0.58),
              (100.0, 0.38), (160.0, 0.18), (240.0, 0.05)]


def _score_working_capital(m: dict, financial: bool, per_year: int = 4) -> Category:
    if financial:
        # A bank has no inventory and no cash-conversion cycle. Scoring one would be inventing
        # a number, so the category is skipped and its weight returns to the others.
        return Category(points=0.0, earned=0.0, parts={"skipped": None})

    cogs = m["cost_of_revenue"]
    dso = [(r / rev * 365) if (r is not None and rev) else None
           for r, rev in zip(m["receivables"], m["revenue"], strict=False)]
    dio = [(i / c * 365) if (i is not None and c) else None
           for i, c in zip(m["inventory"], cogs, strict=False)]
    dpo = [(p / c * 365) if (p is not None and c) else None
           for p, c in zip(m["accounts_payable"], cogs, strict=False)]
    ccc = [(a + b - c) if (a is not None and b is not None and c is not None) else None
           for a, b, c in zip(dso, dio, dpo, strict=False)]

    # Direction carries more weight here than level: a long cycle can be structural to the
    # business, but a LENGTHENING one is cash draining out whatever the industry norm is.
    # Working capital DISCIPLINE: is revenue outrunning the receivables and inventory it is
    # carried on? Revenue +10% against receivables +30% is the classic tell that reported sales
    # are not turning into cash, and it is scored explicitly rather than left to the CCC level.
    rev_g = _yoy(m["revenue"], per_year)
    rec_g = _yoy(m["receivables"], per_year)
    inv_g = _yoy(m["inventory"], per_year)
    spread_knots = [(-0.25, 0.05), (-0.10, 0.25), (0.0, 0.55), (0.05, 0.75), (0.15, 1.0)]
    rec_spread = curve(rev_g - rec_g, spread_knots) if (rev_g is not None
                                                        and rec_g is not None) else None
    inv_spread = curve(rev_g - inv_g, spread_knots) if (rev_g is not None
                                                        and inv_g is not None) else None

    turn = _ratio_series(m["revenue"], m["total_assets"])

    # ROIC is NOT here - it is a return measure and lives in profitability. What belongs here
    # are its operational drivers: how hard the asset base is worked, and how much cash the
    # working-capital cycle ties up getting there.
    parts: dict[str, tuple[float | None, float]] = {
        "cash_conversion_cycle": (_blend(curve(_latest(ccc), _CCC_KNOTS),
                                         _negated(trend(ccc)), 0.35), 0.30),
        "asset_turnover": (_blend(curve(_latest(turn), _TURNOVER_KNOTS), trend(turn)), 0.20),
        "receivables_vs_revenue": (rec_spread, 0.18),
        "inventory_vs_revenue": (inv_spread, 0.14),
        "receivable_days": (curve(_latest(dso), [(15.0, 1.0), (45.0, 0.75), (75.0, 0.5),
                                                 (120.0, 0.25), (200.0, 0.05)]), 0.09),
        "inventory_days": (curve(_latest(dio), [(20.0, 1.0), (60.0, 0.75), (110.0, 0.5),
                                                (180.0, 0.25), (300.0, 0.05)]), 0.09),
    }
    return _weigh(parts, CATEGORY_POINTS["working_capital"])


# ── the metric extract, and the score ───────────────────────────────────────────────────
_INCOME_KEYS = ("revenue", "cost_of_revenue", "gross_profit", "operating_income", "ebitda",
                "net_income", "eps", "weighted_shares", "interest_expense",
                "income_before_tax", "income_tax_expense")
_BALANCE_KEYS = ("total_assets", "total_equity", "total_debt", "current_assets",
                 "current_liabilities", "inventory", "receivables", "accounts_payable",
                 "cash_and_equivalents", "short_term_investments")
_CASHFLOW_KEYS = ("operating_cash_flow", "capital_expenditure", "free_cash_flow")

# Without these nothing meaningful can be said, so a company missing them is scored None rather
# than given a number built out of the handful of fields that happened to survive.
_ESSENTIAL = ("revenue", "net_income", "total_assets", "total_equity")
# Insurers and banks file premiums and interest income, not "revenue", and the source labels
# them accordingly - so every PSX insurer arrived with twenty periods of everything EXCEPT a
# revenue line and was scored None. Their returns come off assets and equity anyway; the
# margin sub-scores simply drop out and profitability renormalises over what remains.
_ESSENTIAL_FINANCIAL = ("net_income", "total_assets", "total_equity")


def _extract(statements: dict[str, list[dict]]) -> dict[str, list[float | None]]:
    inc = statements.get("income") or []
    bal = statements.get("balance") or []
    cf = statements.get("cashflow") or []
    out: dict[str, list[float | None]] = {}
    for key in _INCOME_KEYS:
        out[key] = _series(inc, key)
    for key in _BALANCE_KEYS:
        out[key] = _series(bal, key)
    for key in _CASHFLOW_KEYS:
        out[key] = _series(cf, key)
    out["cash"] = out["cash_and_equivalents"]
    return out


GRADES = ((90, "Exceptional"), (80, "Excellent"), (70, "Good"),
          (60, "Acceptable"), (50, "Weak"), (40, "Poor"))


def grade_for(score: float | None) -> str:
    if score is None:
        return "Unrated"
    for cutoff, label in GRADES:
        if score >= cutoff:
            return label
    return "Very Poor"


@dataclass(slots=True)
class FundamentalScore:
    score: float | None
    grade: str
    categories: dict[str, dict[str, Any]]
    metrics: dict[str, float | None]
    flags: list[str]
    periods: int


def score_fundamentals(statements: dict[str, list[dict]],
                       sector: str | None = None,
                       peers: dict[str, float] | None = None) -> FundamentalScore:
    """The 0-100 Fundamental Quality Score for one company.

    `statements` are the stored TTM rows, newest first - already trailing twelve months, so
    nothing here re-rolls them. `sector` decides whether industrial metrics apply at all (a
    bank has no cash-conversion cycle); `peers` carries industry median margins so a
    structurally thin-margin business is judged against its own industry. There is no country
    input - the same figures score the same everywhere.
    """
    m = _extract(statements)
    per_year = periods_per_year(statements.get("income") or [])
    periods = len(_clean(m["revenue"])) or len(_clean(m["net_income"]))

    financial = (sector or "").strip().lower() in FINANCIAL_SECTORS
    required = _ESSENTIAL_FINANCIAL if financial else _ESSENTIAL
    # ONE period is enough to score a level, which is what the CSVs sometimes give for a newly
    # covered company. Growth and every trend need two and simply drop out - the categories
    # renormalise over what could be measured. The alternative is refusing to score a company
    # we hold real statements for.
    if periods < 1 or any(not _clean(m[k]) for k in required):
        return FundamentalScore(score=None, grade="Unrated",
                                categories={}, metrics={}, flags=["insufficient statements"],
                                periods=periods)

    cats: dict[str, Category] = {
        "growth": _score_growth(m, per_year),
        "profitability": _score_profitability(m, peers, financial),
    }
    cats["cash_flow"], flags = _score_cash_flow(m, per_year)
    cats["balance_sheet"] = _score_balance_sheet(m, financial)
    cats["liquidity"] = _score_liquidity(m, financial)
    cats["working_capital"] = _score_working_capital(m, financial, per_year)

    # Renormalise over the categories that applied. A bank skips working capital, so its score
    # is out of 95 rescaled to 100 - not 95 out of 100, which would cap every bank at 95.
    live = sum(c.points for c in cats.values())
    earned = sum(c.earned for c in cats.values())
    score = round(100 * earned / live, 2) if live else None

    return FundamentalScore(
        score=score,
        grade=grade_for(score),
        categories={k: {"earned": round(c.earned, 2), "points": c.points, "parts": c.parts}
                    for k, c in cats.items()},
        metrics=_headline_metrics(m, per_year),
        flags=flags,
        periods=periods,
    )


def _headline_metrics(m: dict, per_year: int = 4) -> dict[str, float | None]:
    """The current TTM figures behind the score, for the scorecard."""
    def last(series: list[float | None]) -> float | None:
        return _latest(series)

    rev = m["revenue"]
    fcf = m["free_cash_flow"]
    if not _clean(fcf):
        fcf = [(c - abs(x)) if (c is not None and x is not None) else None
               for c, x in zip(m["operating_cash_flow"], m["capital_expenditure"],
                               strict=False)]
    out = {
        "revenue_growth": _yoy(rev, per_year),
        "revenue_cagr_3y": _cagr(rev, 3, per_year),
        "revenue_cagr_5y": _cagr(rev, 5, per_year),
        "operating_profit_growth": _yoy(m["operating_income"], per_year),
        "net_income_growth": _yoy(m["net_income"], per_year),
        "eps_growth": _yoy(m["eps"], per_year),
        "fcf_growth": _yoy(fcf, per_year),
        "gross_margin": last(_ratio_series(m["gross_profit"], rev)),
        "ebitda_margin": last(_ratio_series(m["ebitda"], rev)),
        "operating_margin": last(_ratio_series(m["operating_income"], rev)),
        "net_margin": last(_ratio_series(m["net_income"], rev)),
        "roe": last(_ratio_series(m["net_income"], m["total_equity"])),
        "roa": last(_ratio_series(m["net_income"], m["total_assets"])),
        "roic": last(_roic_series(m)),
        "asset_turnover": last(_ratio_series(rev, m["total_assets"])),
        "cfo_to_net_income": last(_ratio_series(m["operating_cash_flow"], m["net_income"])),
        "fcf_margin": last(_ratio_series(fcf, rev)),
        "fcf_to_net_income": last(_ratio_series(fcf, m["net_income"])),
        "debt_to_equity": last(_ratio_series(m["total_debt"], m["total_equity"])),
        "interest_coverage": last(_ratio_series(
            m["operating_income"], [abs(v) if v else None for v in m["interest_expense"]])),
    }
    return {k: (round(v, 4) if v is not None else None) for k, v in out.items()}
