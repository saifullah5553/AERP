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
    """Run the nine quality tests. `passed` requires the non-negotiables (positive operating
    cash flow, rising EPS) plus a majority of BOTH the growth and cash pillars - growth and
    cash are the thesis, so neither can be waved through by the other."""
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

    reasons = [k for k, v in checks.items() if v is False]
    if not growth_ok:
        reasons.append("growth_pillar_weak")
    if not cash_ok:
        reasons.append("cash_pillar_weak")

    # Score is pillar-weighted, not a flat tally: growth and cash decide quality, debt is a
    # guardrail. Only scored when enough tests have data - otherwise "1 of 1 check passed"
    # would render as a perfect 100 for a company we know almost nothing about.
    score = None
    if known >= 5:
        def _pillar(keys: tuple[str, ...]) -> float | None:
            vals = [checks[k] for k in keys if checks.get(k) is not None]
            return (100.0 * sum(vals) / len(vals)) if vals else None

        g, c, d = _pillar(_GROWTH_CHECKS), _pillar(_CASH_CHECKS), _pillar(_DEBT_CHECKS)
        parts = [(g, 0.45), (c, 0.40), (d, 0.15)]
        avail = [(v, w) for v, w in parts if v is not None]
        if avail:
            base = sum(v * w for v, w in avail) / sum(w for _v, w in avail)
            # Reward the magnitude of growth and cash build, not just their direction.
            bonus = 0.0
            for key, cap in (("revenue_growth", 0.5), ("eps_growth", 1.0), ("cash_growth", 1.0)):
                gv = metrics.get(key)
                if gv is not None:
                    bonus += max(-1.0, min(gv / cap, 1.0)) * 4.0
            score = round(max(0.0, min(100.0, base + bonus)), 2)

    return QualityResult(passed=passed, score=score, checks=checks,
                         metrics=metrics, reasons=reasons)
