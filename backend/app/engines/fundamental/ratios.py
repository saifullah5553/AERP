"""Financial-ratio computation from stored statements.

Inputs are lists of statement-shaped objects (ORM rows or test doubles) sorted
**ascending by fiscal_date** — oldest first, newest last — plus optional market
inputs (price/shares/market cap) needed for valuation ratios. Every field is
``None`` when its inputs are missing; nothing is invented.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.engines.common import cagr, f, growth, safe_div


@dataclass(slots=True)
class MarketInputs:
    price: float | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None

    def resolved_market_cap(self) -> float | None:
        if self.market_cap is not None:
            return self.market_cap
        if self.price is not None and self.shares_outstanding is not None:
            return self.price * self.shares_outstanding
        return None


@dataclass(slots=True)
class RatioSet:
    # Profitability
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    roic: float | None = None
    # Growth
    revenue_growth: float | None = None
    revenue_cagr_3y: float | None = None
    eps_growth: float | None = None
    eps_cagr_3y: float | None = None
    # Leverage / liquidity
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    interest_coverage: float | None = None
    # Cash flow
    free_cash_flow: float | None = None
    fcf_margin: float | None = None
    # Dividends
    dividend_yield: float | None = None
    payout_ratio: float | None = None
    dividend_growth: float | None = None
    # Valuation
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    price_to_sales: float | None = None
    price_to_book: float | None = None
    ev_to_ebitda: float | None = None
    enterprise_value: float | None = None
    book_value_per_share: float | None = None
    # Health (filled by the health module, kept here for a single persisted row)
    altman_z: float | None = None
    piotroski_f: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ebit(income: Any) -> float | None:
    return f(getattr(income, "ebit", None)) or f(getattr(income, "operating_income", None))


def compute_ratios(
    incomes: list[Any],
    balances: list[Any],
    cashflows: list[Any],
    market: MarketInputs | None = None,
) -> RatioSet:
    r = RatioSet()
    market = market or MarketInputs()

    inc = incomes[-1] if incomes else None
    inc_prev = incomes[-2] if len(incomes) >= 2 else None
    bal = balances[-1] if balances else None
    cf = cashflows[-1] if cashflows else None

    # ── Profitability ────────────────────────────────────────
    if inc is not None:
        revenue = f(inc.revenue)
        net_income = f(inc.net_income)
        gross_profit = f(inc.gross_profit)
        if gross_profit is None and revenue is not None:
            cost = f(inc.cost_of_revenue)
            gross_profit = revenue - cost if cost is not None else None
        r.gross_margin = safe_div(gross_profit, revenue)
        r.operating_margin = safe_div(f(inc.operating_income), revenue)
        r.net_margin = safe_div(net_income, revenue)

        # ROE / ROA use average equity/assets when a prior period exists.
        equity = _avg(bal, balances, "total_equity")
        assets = _avg(bal, balances, "total_assets")
        r.roe = safe_div(net_income, equity)
        r.roa = safe_div(net_income, assets)
        r.roic = _roic(inc, bal)

    # ── Growth ───────────────────────────────────────────────
    if inc is not None and inc_prev is not None:
        r.revenue_growth = growth(f(inc.revenue), f(inc_prev.revenue))
        r.eps_growth = growth(f(inc.eps), f(inc_prev.eps))

    rev_window = [f(s.revenue) for s in incomes[-4:]]
    if len(rev_window) >= 2 and rev_window[0] and rev_window[-1]:
        r.revenue_cagr_3y = cagr(rev_window[0], rev_window[-1], len(rev_window) - 1)
    eps_window = [f(s.eps) for s in incomes[-4:]]
    if len(eps_window) >= 2 and eps_window[0] and eps_window[-1]:
        r.eps_cagr_3y = cagr(eps_window[0], eps_window[-1], len(eps_window) - 1)

    # ── Leverage / liquidity ─────────────────────────────────
    if bal is not None:
        total_debt = f(bal.total_debt)
        if total_debt is None:
            std, ltd = f(bal.short_term_debt), f(bal.long_term_debt)
            total_debt = (std or 0) + (ltd or 0) if (std or ltd) else None
        equity = f(bal.total_equity)
        r.debt_to_equity = safe_div(total_debt, equity)
        r.current_ratio = safe_div(f(bal.current_assets), f(bal.current_liabilities))
        r.quick_ratio = safe_div(
            _sub(f(bal.current_assets), f(bal.inventory)), f(bal.current_liabilities)
        )
    if inc is not None:
        interest = f(inc.interest_expense)
        r.interest_coverage = safe_div(_ebit(inc), abs(interest) if interest else None)

    # ── Cash flow ────────────────────────────────────────────
    if cf is not None:
        fcf = f(cf.free_cash_flow)
        if fcf is None:
            ocf, capex = f(cf.operating_cash_flow), f(cf.capital_expenditure)
            fcf = ocf + capex if ocf is not None and capex is not None else None
        r.free_cash_flow = fcf
        if inc is not None:
            r.fcf_margin = safe_div(fcf, f(inc.revenue))

    # ── Dividends ────────────────────────────────────────────
    if cf is not None and inc is not None:
        div_paid = f(cf.dividends_paid)  # outflow, typically negative
        if div_paid is not None:
            div_abs = abs(div_paid)
            r.payout_ratio = safe_div(div_abs, f(inc.net_income))
            shares = market.shares_outstanding or f(inc.weighted_shares)
            dps = safe_div(div_abs, shares)
            r.dividend_yield = safe_div(dps, market.price)
    div_series = [
        abs(f(c.dividends_paid)) for c in cashflows[-2:] if f(c.dividends_paid) is not None
    ]
    if len(div_series) == 2:
        r.dividend_growth = growth(div_series[-1], div_series[0])

    # ── Valuation ────────────────────────────────────────────
    if inc is not None:
        mcap = market.resolved_market_cap()
        net_income = f(inc.net_income)
        revenue = f(inc.revenue)
        r.pe_ratio = safe_div(mcap, net_income) if net_income and net_income > 0 else None
        r.price_to_sales = safe_div(mcap, revenue)
        if bal is not None:
            equity = f(bal.total_equity)
            r.price_to_book = safe_div(mcap, equity)
            shares = market.shares_outstanding or f(inc.weighted_shares)
            r.book_value_per_share = safe_div(equity, shares)
            cash = f(bal.cash_and_equivalents)
            debt = f(bal.total_debt)
            if mcap is not None and debt is not None:
                r.enterprise_value = mcap + debt - (cash or 0)
                r.ev_to_ebitda = safe_div(r.enterprise_value, f(inc.ebitda))
        if r.pe_ratio is not None and r.eps_growth and r.eps_growth > 0:
            r.peg_ratio = r.pe_ratio / (r.eps_growth * 100)

    return r


def _avg(latest: Any, series: list[Any], attr: str) -> float | None:
    """Average of the latest and prior value of ``attr``; latest alone if no prior."""
    if latest is None:
        return None
    cur = f(getattr(latest, attr))
    if cur is None:
        return None
    if len(series) >= 2:
        prev = f(getattr(series[-2], attr))
        if prev is not None:
            return (cur + prev) / 2
    return cur


def _roic(inc: Any, bal: Any) -> float | None:
    if bal is None:
        return None
    ebit = _ebit(inc)
    ibt, tax = f(inc.income_before_tax), f(inc.income_tax_expense)
    tax_rate = safe_div(tax, ibt)
    if ebit is None or tax_rate is None:
        return None
    tax_rate = max(0.0, min(1.0, tax_rate))
    nopat = ebit * (1 - tax_rate)
    debt = f(bal.total_debt) or 0.0
    equity = f(bal.total_equity) or 0.0
    cash = f(bal.cash_and_equivalents) or 0.0
    invested = debt + equity - cash
    return safe_div(nopat, invested if invested != 0 else None)


def _sub(a: float | None, b: float | None) -> float | None:
    if a is None:
        return None
    return a - (b or 0.0)


# Convenience for callers that want the field list (e.g. persistence mapping).
RATIO_FIELDS: list[str] = list(RatioSet.__dataclass_fields__)
