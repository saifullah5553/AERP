"""Fundamental quality gate — "is this a business worth owning at all?"

GROWTH and CASH are the thesis; debt is only a guardrail. The tests are judged over multiple
reported periods so a single good year can't qualify a company:

    GROWTH pillar   1. Revenue rising
                    2. Operating profit rising
                    3. EPS rising
    CASH pillar     4. Operating cash flow positive        (non-negotiable)
                    5. Free cash flow positive             (cash left after capex)
                    6. Earnings backed by cash             (OCF/net income >= 0.7)
                    7. Cash reserves healthy
                    8. Cash building                       (the pile is growing)
    GUARDRAIL       9. Debt low or falling

Qualifying requires a MAJORITY OF EACH PILLAR, not just a tally of any N boxes - so a company
can never pass on low debt and tidy ratios while its growth or cash is deteriorating. The score
is pillar-weighted (growth 45% / cash 40% / debt 15%) and only produced once at least five
tests have data, so a company we know almost nothing about can't render as a perfect 100.

This is a GATE first and a score second: a name either qualifies to be owned or it doesn't, and
the score only ranks the ones that already qualify. The previous engine blended everything into
a single number, letting a weak business surface on strong technicals - exactly the behaviour
the backtests punished.

Statements arrive newest-first (see the export contract), so index 0 is the latest period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The two pillars of the thesis. Growth and cash decide whether a business is worth owning;
# debt is a guardrail, not a reason to buy.
_GROWTH_CHECKS = ("revenue_rising", "operating_profit_rising", "eps_rising")
_CASH_CHECKS = (
    "cash_flow_positive", "free_cash_flow_positive",
    "earnings_backed_by_cash", "cash_reserves_healthy", "cash_building",
)
_DEBT_CHECKS = ("debt_low_or_falling",)

# What the score is actually made of. Weighted per check rather than averaged within a pillar,
# because averaging made every cash test count the same - "cash reserves look healthy" carried
# as much as "the business generates operating cash", which is not how the thesis works.
#
# The four that decide it are growth, operating cash flow, free cash flow and debt: 85% of the
# score between them. The remaining three are corroborating detail, not reasons to own a
# business, so they share 15%.
#
# Weights are renormalised over whatever could be evaluated, so a missing line item never reads
# as a failed test.
CHECK_WEIGHTS: dict[str, float] = {
    # GROWTH - 40%. The thesis: buy businesses that are getting bigger.
    "revenue_rising": 0.1334,
    "operating_profit_rising": 0.1333,
    "eps_rising": 0.1333,
    # CASH - 20%. Operating and free cash flow carry it; the other three corroborate rather
    # than justify, so they take the remainder.
    "cash_flow_positive": 0.07,
    "free_cash_flow_positive": 0.07,
    "earnings_backed_by_cash": 0.025,
    "cash_reserves_healthy": 0.0175,
    "cash_building": 0.0175,
    # DEBT - 20%. A guardrail, but a heavy one: leverage is what turns a bad quarter fatal.
    "debt_low_or_falling": 0.20,
    # VALUATION AND RETURNS - 20%, split evenly.
    #
    # Valuation (10%): a great business bought at any price is not a good investment. These are
    # the only checks that need a quote, so they are the only ones that go unknown for a
    # company we have statements but no price for.
    "earnings_yield_attractive": 0.025,
    "fcf_yield_attractive": 0.025,
    "price_to_book_reasonable": 0.025,
    "margin_of_safety": 0.025,
    # Returns and margins (10%): how well the business converts capital and sales into profit.
    # Growth tells you a company is getting bigger; these tell you whether that is worth
    # anything. Computed from statements alone, so they score even without a quote.
    "roe_strong": 0.025,
    "roa_strong": 0.025,
    "operating_margin_healthy": 0.025,
    "net_margin_healthy": 0.025,
}

_VALUATION_CHECKS = ("earnings_yield_attractive", "fcf_yield_attractive",
                     "price_to_book_reasonable", "margin_of_safety")
_RETURN_CHECKS = ("roe_strong", "roa_strong",
                  "operating_margin_healthy", "net_margin_healthy")

# Thresholds for the valuation pillar. Deliberately plain and absolute rather than relative to
# a sector or an index: a rule you can check by hand is one you can disagree with.
EARNINGS_YIELD_GOOD = 0.05      # P/E <= 20
FCF_YIELD_GOOD = 0.04           # 4% of market cap in free cash flow
PRICE_TO_BOOK_GOOD = 3.0
MARGIN_OF_SAFETY_YIELD = 0.10   # P/E <= 10 - the classic value cushion

ROE_GOOD = 0.15                 # 15% on equity
ROA_GOOD = 0.05                 # 5% on total assets
OPERATING_MARGIN_GOOD = 0.10
NET_MARGIN_GOOD = 0.05


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN guard


def _series(rows: list[dict], key: str, periods: int = 4) -> list[float]:
    """Newest-first values for `key`, oldest→newest, skipping gaps."""
    out: list[float] = []
    for r in rows[:periods]:
        v = _f(r.get(key))
        if v is not None:
            out.append(v)
    return list(reversed(out))  # chronological


def _rising(vals: list[float], tolerance: float = 0.0) -> bool | None:
    """True when the series trends up: latest beats the earliest available point."""
    if len(vals) < 2:
        return None
    first, last = vals[0], vals[-1]
    if first == 0:
        return last > 0
    return (last - first) / abs(first) > tolerance


def _growth(vals: list[float]) -> float | None:
    if len(vals) < 2 or vals[0] == 0:
        return None
    return (vals[-1] - vals[0]) / abs(vals[0])


@dataclass(slots=True)
class QualityResult:
    passed: bool                   # fully strong: majority of BOTH pillars
    score: float | None            # 0-100, only meaningful for names that pass
    checks: dict[str, bool | None] = field(default_factory=dict)
    metrics: dict[str, float | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    improving: bool = False        # not yet fully strong, but the trend is the right way

    @property
    def eligible(self) -> bool:
        """Worth looking at the chart for: strong OR credibly improving.

        A turnaround rarely ticks every box on the print where it turns - earnings recover
        before the balance sheet does. Requiring perfection would mean only ever buying
        businesses whose re-rating has already happened.
        """
        return self.passed or self.improving


def _add_return_checks(checks: dict, metrics: dict, inc: list[dict], bal: list[dict]) -> None:
    """Returns on capital and margins - how good the business is, not how big or how cheap.

    Statement-only, so unlike the valuation tests these are answerable for every company we
    have accounts for.
    """
    for key in _RETURN_CHECKS:
        checks.setdefault(key, None)

    latest_inc = inc[0] if inc else {}
    latest_bal = bal[0] if bal else {}
    net_income = _f(latest_inc.get("net_income"))
    revenue = _f(latest_inc.get("revenue"))
    op_income = _f(latest_inc.get("operating_income"))
    equity = _f(latest_bal.get("total_equity"))
    assets = _f(latest_bal.get("total_assets"))

    roe = net_income / equity if (net_income is not None and equity and equity > 0) else None
    roa = net_income / assets if (net_income is not None and assets and assets > 0) else None
    op_margin = op_income / revenue if (op_income is not None and revenue and revenue > 0) else None
    net_margin = net_income / revenue if (net_income is not None and revenue and revenue > 0) else None

    metrics.update({"roe": roe, "roa": roa,
                    "operating_margin": op_margin, "net_margin": net_margin})
    if roe is not None:
        checks["roe_strong"] = roe >= ROE_GOOD
    if roa is not None:
        checks["roa_strong"] = roa >= ROA_GOOD
    if op_margin is not None:
        checks["operating_margin_healthy"] = op_margin >= OPERATING_MARGIN_GOOD
    if net_margin is not None:
        checks["net_margin_healthy"] = net_margin >= NET_MARGIN_GOOD


def _add_valuation_checks(checks: dict, metrics: dict, inc: list[dict], bal: list[dict],
                          cf: list[dict], market: dict | None) -> None:
    """Is it cheap enough to be worth owning? Only answerable with a price.

    Every check defaults to None. A company we cannot price must not be scored as though it
    were expensive - that would quietly punish exactly the illiquid names where a quote is
    hardest to get.
    """
    for key in _VALUATION_CHECKS:
        checks.setdefault(key, None)
    if not market:
        return

    price = _f(market.get("price"))
    market_cap = _f(market.get("market_cap"))
    shares = _f(market.get("shares"))
    if market_cap is None and price and shares:
        market_cap = price * shares

    latest_inc = inc[0] if inc else {}
    latest_bal = bal[0] if bal else {}
    latest_cf = cf[0] if cf else {}
    eps = _f(latest_inc.get("eps"))
    net_income = _f(latest_inc.get("net_income"))
    equity = _f(latest_bal.get("total_equity"))
    fcf = _f(latest_cf.get("free_cash_flow"))

    # Earnings yield, the inverse of P/E. Used rather than P/E because a loss makes P/E
    # meaningless while a negative yield is still an honest reading.
    earnings_yield = None
    if price and price > 0 and eps is not None:
        earnings_yield = eps / price
    elif market_cap and market_cap > 0 and net_income is not None:
        earnings_yield = net_income / market_cap
    metrics["earnings_yield"] = earnings_yield
    if earnings_yield is not None:
        checks["earnings_yield_attractive"] = earnings_yield >= EARNINGS_YIELD_GOOD
        # Margin of safety: not a valuation model, just a demand to be paid enough for the
        # risk. A doubled earnings yield is the classic cushion.
        checks["margin_of_safety"] = earnings_yield >= MARGIN_OF_SAFETY_YIELD

    fcf_yield = None
    if market_cap and market_cap > 0 and fcf is not None:
        fcf_yield = fcf / market_cap
    metrics["fcf_yield"] = fcf_yield
    if fcf_yield is not None:
        checks["fcf_yield_attractive"] = fcf_yield >= FCF_YIELD_GOOD

    price_to_book = None
    if market_cap and market_cap > 0 and equity and equity > 0:
        price_to_book = market_cap / equity
    metrics["price_to_book"] = price_to_book
    if price_to_book is not None:
        checks["price_to_book_reasonable"] = price_to_book <= PRICE_TO_BOOK_GOOD


def assess_quality(statements: dict[str, list[dict]], min_checks: int = 5,
                   market: dict | None = None) -> QualityResult:
    """Run the quality tests. `passed` requires the non-negotiables (positive operating cash
    flow, rising EPS) plus a majority of BOTH the growth and cash pillars - growth and cash are
    the thesis, so neither can be waved through by the other.

    `market` carries {price, market_cap, shares} when a quote is available. Valuation is scored
    only when it is: absent, those checks stay unknown and the weights renormalise, so a
    company we cannot price is not scored as though it were expensive.

    Valuation never affects `passed`. Whether a business is sound and whether it is cheap are
    different questions, and collapsing them would hide a good company that is merely dear.
    """
    inc = statements.get("income") or []
    bal = statements.get("balance") or []
    cf = statements.get("cashflow") or []

    revenue = _series(inc, "revenue")
    op_income = _series(inc, "operating_income")
    eps = _series(inc, "eps")
    ocf = _series(cf, "operating_cash_flow")
    debt = _series(bal, "total_debt")
    equity = _series(bal, "total_equity") or _series(bal, "retained_earnings")
    cash = _series(bal, "cash_and_equivalents")
    cur_assets = _series(bal, "current_assets")
    cur_liab = _series(bal, "current_liabilities")

    checks: dict[str, bool | None] = {}
    metrics: dict[str, float | None] = {}

    # 1-3: the growth engine of the business.
    checks["revenue_rising"] = _rising(revenue)
    checks["operating_profit_rising"] = _rising(op_income)
    checks["eps_rising"] = _rising(eps)
    metrics["revenue_growth"] = _growth(revenue)
    metrics["operating_profit_growth"] = _growth(op_income)
    metrics["eps_growth"] = _growth(eps)

    # 4: debt low or falling. "Low" is judged against equity when we have it.
    de = None
    if debt and equity and equity[-1] not in (0, None):
        de = debt[-1] / abs(equity[-1])
    metrics["debt_to_equity"] = de
    falling_debt = None
    if len(debt) >= 2:
        falling_debt = debt[-1] <= debt[0]
    metrics["debt_change"] = _growth(debt)
    if de is not None or falling_debt is not None:
        checks["debt_low_or_falling"] = bool((de is not None and de < 1.0) or falling_debt)
    else:
        checks["debt_low_or_falling"] = None

    # 5: cash generation - non-negotiable. Latest operating cash flow must be positive.
    checks["cash_flow_positive"] = (ocf[-1] > 0) if ocf else None
    metrics["operating_cash_flow"] = ocf[-1] if ocf else None

    # 5b: free cash flow - cash left AFTER the capex needed to keep growing. A company can
    # show positive operating cash flow and still consume cash once capex is paid for.
    fcf = _series(cf, "free_cash_flow")
    if not fcf:
        capex = _series(cf, "capital_expenditure")
        if ocf and capex and len(ocf) == len(capex):
            fcf = [o - abs(c) for o, c in zip(ocf, capex, strict=False)]
    checks["free_cash_flow_positive"] = (fcf[-1] > 0) if fcf else None
    metrics["free_cash_flow"] = fcf[-1] if fcf else None

    # 5c: earnings backed by cash. Profit that never becomes cash is the classic warning sign,
    # so compare operating cash flow against net income.
    net_income = _series(inc, "net_income")
    conv = None
    if ocf and net_income and net_income[-1] > 0:
        conv = ocf[-1] / net_income[-1]
    metrics["cash_conversion"] = conv
    checks["earnings_backed_by_cash"] = (conv >= 0.7) if conv is not None else None

    # 6b: is the cash pile actually building? A growing balance funds growth without dilution.
    checks["cash_building"] = _rising(cash) if len(cash) >= 2 else None
    metrics["cash_growth"] = _growth(cash)

    # 6: reserves - cash against short-term obligations, or a healthy current ratio.
    cash_ratio = None
    if cash and cur_liab and cur_liab[-1] not in (0, None):
        cash_ratio = cash[-1] / abs(cur_liab[-1])
    current_ratio = None
    if cur_assets and cur_liab and cur_liab[-1] not in (0, None):
        current_ratio = cur_assets[-1] / abs(cur_liab[-1])
    metrics["cash_to_current_liabilities"] = cash_ratio
    metrics["current_ratio"] = current_ratio
    if cash_ratio is not None or current_ratio is not None:
        checks["cash_reserves_healthy"] = bool(
            (cash_ratio is not None and cash_ratio >= 0.20)
            or (current_ratio is not None and current_ratio >= 1.2)
        )
    else:
        checks["cash_reserves_healthy"] = None

    trues = sum(1 for v in checks.values() if v is True)
    known = sum(1 for v in checks.values() if v is not None)

    # Non-negotiables: a business that burns cash or shrinks EPS is not "fundamentally strong"
    # however many other boxes it ticks.
    must_pass = checks.get("cash_flow_positive") is not False and checks.get("eps_rising") is True
    growth_known = [checks[k] for k in _GROWTH_CHECKS if checks.get(k) is not None]
    cash_known = [checks[k] for k in _CASH_CHECKS if checks.get(k) is not None]
    # Growth and cash are the thesis: require a majority of each pillar, not just a count of
    # any five boxes. A company can no longer qualify on low debt + tidy ratios alone.
    growth_ok = bool(growth_known) and sum(growth_known) >= max(2, len(growth_known) - 1)
    cash_ok = bool(cash_known) and sum(cash_known) >= max(2, len(cash_known) - 1)
    passed = bool(
        must_pass and known >= 5 and growth_ok and cash_ok
        and trues >= min(min_checks, known)
    )

    _add_valuation_checks(checks, metrics, inc, bal, cf, market)
    _add_return_checks(checks, metrics, inc, bal)

    reasons = [k for k, v in checks.items() if v is False]
    if not growth_ok:
        reasons.append("growth_pillar_weak")
    if not cash_ok:
        reasons.append("cash_pillar_weak")

    # "Improving" — not yet strong enough to pass outright, but heading the right way. The
    # business must still be growing (that's the thesis) and must not be burning cash; what it
    # is allowed to lack is the full cash-pillar majority, which typically lags a turnaround.
    improving = bool(
        not passed
        and checks.get("cash_flow_positive") is not False
        and growth_ok
        and (checks.get("eps_rising") is True or checks.get("operating_profit_rising") is True)
    )

    # Score is pillar-weighted, not a flat tally: growth and cash decide quality, debt is a
    # guardrail. Only scored when enough tests have data - otherwise "1 of 1 check passed"
    # would render as a perfect 100 for a company we know almost nothing about.
    score = None
    if known >= 5:
        avail = [(100.0 if checks[k] else 0.0, w)
                 for k, w in CHECK_WEIGHTS.items() if checks.get(k) is not None]
        if avail:
            # Renormalised over the checks we could actually evaluate, so a company missing a
            # line item is not scored as if it had failed that test.
            base = sum(v * w for v, w in avail) / sum(w for _v, w in avail)
            # Reward the magnitude of growth and cash build, not just their direction.
            bonus = 0.0
            for key, cap in (("revenue_growth", 0.5), ("eps_growth", 1.0), ("cash_growth", 1.0)):
                gv = metrics.get(key)
                if gv is not None:
                    bonus += max(-1.0, min(gv / cap, 1.0)) * 4.0
            score = round(max(0.0, min(100.0, base + bonus)), 2)

    return QualityResult(passed=passed, score=score, checks=checks,
                         metrics=metrics, reasons=reasons, improving=improving)
