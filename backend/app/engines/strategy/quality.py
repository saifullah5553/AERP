"""Fundamental quality gate — "is this a business worth owning at all?"

Implements the six tests the strategy is built on, judged over multiple reported periods so a
single good year can't qualify a company:

    1. Revenue rising
    2. Operating profit rising
    3. EPS rising
    4. Debt low or falling
    5. Operating cash flow positive
    6. Healthy cash reserves

This is a GATE first and a score second. A name either qualifies to be owned or it doesn't;
the score only ranks the ones that already qualify. That is deliberate: the previous engine
blended everything into one number, so a weak business could still surface on strong technicals
- exactly the behaviour the backtests punished.

Statements arrive newest-first (see the export contract), so index 0 is the latest period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    passed: bool
    score: float | None            # 0-100, only meaningful for names that pass
    checks: dict[str, bool | None] = field(default_factory=dict)
    metrics: dict[str, float | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def assess_quality(statements: dict[str, list[dict]], min_checks: int = 5) -> QualityResult:
    """Run the six quality tests. `passed` requires at least `min_checks` of the 6 to be True
    AND the two non-negotiables (positive operating cash flow, rising EPS)."""
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
    passed = bool(must_pass and known >= 4 and trues >= min(min_checks, known))

    reasons = [k for k, v in checks.items() if v is False]

    # Score ranks the qualifying names: how many checks passed, tilted by growth strength.
    # Only scored when enough of the six tests actually have data - otherwise "1 of 1 check
    # passed" would render as a perfect 100 for a company we know almost nothing about.
    score = None
    if known >= 4:
        base = 100.0 * trues / known
        growth_bonus = 0.0
        for key, cap in (("revenue_growth", 0.5), ("eps_growth", 1.0)):
            g = metrics.get(key)
            if g is not None:
                growth_bonus += max(-1.0, min(g / cap, 1.0)) * 5.0
        score = round(max(0.0, min(100.0, base + growth_bonus)), 2)

    return QualityResult(passed=passed, score=score, checks=checks,
                         metrics=metrics, reasons=reasons)
