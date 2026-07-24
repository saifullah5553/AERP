"""Composite financial-health scores: Piotroski F-Score and Altman Z-Score.

Both are computed from stored statements only. When the inputs required for a
criterion are missing, that criterion is simply not credited (F-Score) or the
whole score is ``None`` (Z-Score) — never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.engines.common import f, safe_div


@dataclass(slots=True)
class PiotroskiResult:
    score: int | None
    criteria: dict[str, bool] = field(default_factory=dict)


def piotroski_f_score(
    incomes: list[Any], balances: list[Any], cashflows: list[Any]
) -> PiotroskiResult:
    """9-point Piotroski F-Score. Needs the two most recent annual periods."""
    if len(incomes) < 2 or len(balances) < 2 or not cashflows:
        return PiotroskiResult(score=None)

    inc, inc_p = incomes[-1], incomes[-2]
    bal, bal_p = balances[-1], balances[-2]
    cf = cashflows[-1]

    assets = f(bal.total_assets)
    assets_p = f(bal_p.total_assets)
    ni = f(inc.net_income)
    ni_p = f(inc_p.net_income)
    roa = safe_div(ni, assets)
    roa_p = safe_div(ni_p, assets_p)
    ocf = f(cf.operating_cash_flow)

    c: dict[str, bool] = {}
    # Profitability
    c["positive_roa"] = bool(roa is not None and roa > 0)
    c["positive_ocf"] = bool(ocf is not None and ocf > 0)
    c["roa_improved"] = bool(roa is not None and roa_p is not None and roa > roa_p)
    c["accruals"] = bool(
        ocf is not None and ni is not None and assets and (ocf / assets) > (ni / assets)
    )
    # Leverage, liquidity, dilution
    ltd_ratio = safe_div(f(bal.long_term_debt), assets)
    ltd_ratio_p = safe_div(f(bal_p.long_term_debt), assets_p)
    c["lower_leverage"] = bool(
        ltd_ratio is not None and ltd_ratio_p is not None and ltd_ratio < ltd_ratio_p
    )
    cr = safe_div(f(bal.current_assets), f(bal.current_liabilities))
    cr_p = safe_div(f(bal_p.current_assets), f(bal_p.current_liabilities))
    c["higher_current_ratio"] = bool(cr is not None and cr_p is not None and cr > cr_p)
    shares = f(inc.weighted_shares)
    shares_p = f(inc_p.weighted_shares)
    c["no_dilution"] = bool(shares is not None and shares_p is not None and shares <= shares_p)
    # Operating efficiency
    gm = safe_div(f(inc.gross_profit), f(inc.revenue))
    gm_p = safe_div(f(inc_p.gross_profit), f(inc_p.revenue))
    c["higher_margin"] = bool(gm is not None and gm_p is not None and gm > gm_p)
    at = safe_div(f(inc.revenue), assets)
    at_p = safe_div(f(inc_p.revenue), assets_p)
    c["higher_turnover"] = bool(at is not None and at_p is not None and at > at_p)

    return PiotroskiResult(score=sum(1 for v in c.values() if v), criteria=c)


def altman_z_score(inc: Any, bal: Any, market_cap: float | None) -> float | None:
    """Altman Z-Score for public manufacturers.

    Z = 1.2·A + 1.4·B + 3.3·C + 0.6·D + 1.0·E, where D uses market value of equity
    (falls back to book equity, which yields the Z'-style variant) over total
    liabilities. Returns ``None`` if core balance-sheet inputs are missing.
    """
    if inc is None or bal is None:
        return None
    total_assets = f(bal.total_assets)
    total_liabilities = f(bal.total_liabilities)
    if not total_assets or not total_liabilities:
        return None

    working_capital = _sub(f(bal.current_assets), f(bal.current_liabilities))
    retained = f(bal.retained_earnings)
    ebit = f(inc.ebit) or f(inc.operating_income)
    revenue = f(inc.revenue)
    equity_value = market_cap if market_cap is not None else f(bal.total_equity)

    a = safe_div(working_capital, total_assets)
    b = safe_div(retained, total_assets)
    cc = safe_div(ebit, total_assets)
    d = safe_div(equity_value, total_liabilities)
    e = safe_div(revenue, total_assets)
    if None in (a, b, cc, d, e):
        return None
    return 1.2 * a + 1.4 * b + 3.3 * cc + 0.6 * d + 1.0 * e


def _sub(a: float | None, b: float | None) -> float | None:
    if a is None:
        return None
    return a - (b or 0.0)
