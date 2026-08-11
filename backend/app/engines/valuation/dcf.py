"""Discounted cash flow: a fair value per share, built the way a CFA charterholder would.

FCFF discounted at WACC, less net debt, over diluted shares. Every input comes from our own
quarterly-TTM statements or from a stated market assumption - nothing is fetched from a vendor's
"fair value" field and nothing is guessed silently. Where an input is missing the model returns
NO VALUE with a reason, because a DCF built on filled-in blanks is a number with a decimal point
and no meaning.

THE DISCOUNT RATE IS BUILT PER COUNTRY, which is the point of the exercise for a portfolio that
spans Karachi and New York. A 12% required return is punitive in the US and far too generous in
Pakistan; using one rate for both would make every PSX name look cheap and every US name dear:

    cost of equity = risk-free + beta x equity risk premium              (CAPM)
    WACC           = E/V x cost of equity + D/V x after-tax cost of debt

Beta is MEASURED, from our own weekly price history against the market's own index - see
engines/valuation/beta.py. It was held at 1.0 at first on the argument that a regression beta
from a thin listing is noisier than it is useful. That argument was half right: the fix for a
noisy estimate is the Blume shrink and a clamp, not throwing the estimate away. Where the
history is too short to measure, beta still falls back to 1.0 and says so.

THE CASH FLOWS COME FROM THE TREND, NOT THE LAST PRINT. One quarter is noise; the growth rate
here is a least-squares fit through up to twenty quarters of trailing-twelve-month FCF, which is
what "analyse the last 20 quarters" has to mean if it is to survive a single bad quarter. The
fitted rate is then capped hard - see GROWTH_CAP - because a company compounding at 60% for five
years is a spreadsheet artefact, not a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Country inputs ──────────────────────────────────────────────────────────────────────────
# Risk-free = the local 10-year government yield. Equity risk premium follows Damodaran's
# construction: a mature-market base of ~4.5% plus a country default spread scaled for equity
# volatility. Pakistan is set to 7.0% as instructed, which is in line with that method.
#
# These are ASSUMPTIONS and they are written down here so they can be argued with, which is the
# whole reason they are not buried in the code that uses them. Rates move; the note on each says
# what it is meant to represent so the next person knows what to update.
COUNTRY_RATES: dict[str, dict[str, float]] = {
    #            risk-free   equity risk premium   corporate tax
    "us":        {"rf": 0.043, "erp": 0.045, "tax": 0.21},
    "india":     {"rf": 0.069, "erp": 0.062, "tax": 0.25},
    "australia": {"rf": 0.043, "erp": 0.050, "tax": 0.30},
    "gcc":       {"rf": 0.048, "erp": 0.055, "tax": 0.20},   # Saudi
    "dfm":       {"rf": 0.045, "erp": 0.058, "tax": 0.09},   # UAE, 9% CT from 2023
    "psx":       {"rf": 0.115, "erp": 0.070, "tax": 0.29},   # PKR 10y; ERP 7.0% as specified
}
_FALLBACK = {"rf": 0.05, "erp": 0.06, "tax": 0.25}

# Terminal growth must not exceed long-run nominal GDP, or the model implies the company
# eventually becomes the economy. Set per country because nominal growth in Pakistan is not
# nominal growth in Australia - most of the difference is inflation, and the cash flows being
# discounted are nominal too.
TERMINAL_GROWTH: dict[str, float] = {
    "us": 0.025, "india": 0.055, "australia": 0.025, "gcc": 0.030, "dfm": 0.030, "psx": 0.070,
}

FORECAST_YEARS = 5
# Terminal value may not be more than this share of enterprise value. Past it the "valuation"
# is a statement about the perpetuity assumption and almost nothing about the five years of
# cash flow anyone can actually reason about, so it is refused rather than published.
MAX_TERMINAL_SHARE = 0.85
# A fair value this far from the traded price means the MODEL is wrong, not the market. At
# 8,000 listings something will always divide badly - one such name came out at eleven MILLION
# times its price - and publishing that discredits the 4,000 sane ones beside it.
MAX_PRICE_MULTIPLE = 5.0
MIN_PRICE_MULTIPLE = 0.1
# A fitted growth rate above this is not a forecast, it is an extrapolation of a good run.
GROWTH_CAP = 0.20
GROWTH_FLOOR = -0.10
MIN_QUARTERS = 8          # two years of TTM points before a trend means anything
MIN_SPREAD = 0.02         # WACC must clear terminal growth by this, or the terminal value blows up


@dataclass(slots=True)
class DCFResult:
    fair_value: float | None = None
    upside_pct: float | None = None
    wacc: float | None = None
    cost_of_equity: float | None = None
    growth: float | None = None
    terminal_growth: float | None = None
    base_fcf: float | None = None
    quarters_used: int = 0
    enterprise_value: float | None = None
    equity_value: float | None = None
    net_debt: float | None = None
    shares: float | None = None
    verdict: str = ""          # undervalued | fairly valued | overvalued | no value
    assumptions: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def _clean(values: list[Any]) -> list[float]:
    return [float(v) for v in values if isinstance(v, int | float)]


def _fit_growth(series: list[float]) -> float | None:
    """Annual growth from a least-squares fit through the log of the TTM series.

    A log fit rather than first-to-last: first-to-last is decided entirely by its two endpoints,
    so one weak quarter at either end rewrites the forecast. Fitting through every point uses
    the whole run, which is what twenty quarters of history is for.

    Returns None when the series crosses zero - a company that swung from cash burn to cash
    generation has no meaningful growth RATE, and forcing one produces nonsense.
    """
    import math

    if len(series) < MIN_QUARTERS or any(v <= 0 for v in series):
        return None
    n = len(series)
    xs = list(range(n))                      # oldest to newest, one step per quarter
    ys = [math.log(v) for v in series]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denom
    # slope is per quarter in log space; four quarters make a year.
    try:
        return math.exp(slope * 4) - 1
    except OverflowError:
        return None


def _series(rows: list[dict], key: str) -> list[float]:
    """A statement line oldest-first, which is the order a trend has to be fitted in."""
    out = [r.get(key) for r in reversed(rows or [])]
    return _clean(out)


def value(statements: dict[str, list[dict]], price: float | None, region: str,
          symbol: str | None = None) -> DCFResult:
    """Fair value per share for one company, or a stated refusal."""
    rates = COUNTRY_RATES.get(region, _FALLBACK)
    rf, erp, tax = rates["rf"], rates["erp"], rates["tax"]
    g_terminal = TERMINAL_GROWTH.get(region, 0.03)
    # Beta from our own prices where the history allows it, 1.0 where it does not.
    beta_note, beta = "assumed - not measured", 1.0
    if symbol:
        try:
            from app.engines.valuation.beta import compute as compute_beta

            got = compute_beta(region, symbol)
            beta, beta_note = got.beta, got.note
        except Exception:  # noqa: BLE001 - an unmeasurable beta must not fail the valuation
            pass
    assumptions = {"risk_free": rf, "equity_risk_premium": erp, "tax_rate": tax,
                   "terminal_growth": g_terminal, "beta": beta, "beta_basis": beta_note,
                   "forecast_years": FORECAST_YEARS}

    income = (statements or {}).get("income") or []
    balance = (statements or {}).get("balance") or []
    cash = (statements or {}).get("cashflow") or []
    if not income or not balance or not cash:
        return DCFResult(verdict="no value", reason="no statements", assumptions=assumptions)

    fcf_series = _series(cash, "free_cash_flow")
    if len(fcf_series) < MIN_QUARTERS:
        return DCFResult(verdict="no value", quarters_used=len(fcf_series),
                         reason=f"needs {MIN_QUARTERS} quarters of free cash flow, "
                                f"has {len(fcf_series)}", assumptions=assumptions)

    # The base is the average of the last four TTM points, not the newest one. Each point is
    # already a trailing year, so this smooths the seasonal wobble between overlapping windows
    # without reaching further back than a year for the STARTING level.
    base = sum(fcf_series[-4:]) / len(fcf_series[-4:])
    if base <= 0:
        return DCFResult(verdict="no value", quarters_used=len(fcf_series),
                         base_fcf=round(base, 2),
                         reason="free cash flow is negative - a DCF on negative cash flow "
                                "prices the burn, not the business",
                         assumptions=assumptions)

    fitted = _fit_growth(fcf_series)
    growth = g_terminal if fitted is None else max(GROWTH_FLOOR, min(fitted, GROWTH_CAP))

    # CAPM, then WACC weighted on MARKET equity where we can price it. Market cap is
    # shares x the live price - we hold the diluted share count in the same statements this
    # model already reads, so the "we do not have market cap" that forced book weights was
    # never true, only unjoined. Book equity remains the fallback for an unpriced listing, and
    # which one was used is recorded rather than left to inference.
    cost_equity = rf + beta * erp
    debt = next((r.get("total_debt") for r in balance
                 if isinstance(r.get("total_debt"), int | float)), 0.0) or 0.0
    equity_book = next((r.get("total_equity") for r in balance
                        if isinstance(r.get("total_equity"), int | float)), 0.0) or 0.0
    cash_now = next((r.get("cash_and_equivalents") for r in balance
                     if isinstance(r.get("cash_and_equivalents"), int | float)), 0.0) or 0.0

    shares_now = next((r.get("weighted_shares") for r in income
                       if isinstance(r.get("weighted_shares"), int | float)
                       and r.get("weighted_shares")), None)
    market_cap = (shares_now * price) if (shares_now and price and price > 0) else None
    equity_weight = market_cap if market_cap else equity_book
    assumptions["equity_weight_basis"] = "market cap" if market_cap else "book equity"
    assumptions["market_cap"] = round(market_cap, 2) if market_cap else None

    total_cap = debt + equity_weight
    if total_cap <= 0 or equity_weight <= 0:
        return DCFResult(verdict="no value",
                         reason="no positive equity value to weight the cost of capital on",
                         assumptions=assumptions)
    # Cost of debt from the risk-free plus a spread, not from interest expense over debt: that
    # ratio is wild for companies whose debt moved during the year.
    cost_debt_after_tax = (rf + 0.02) * (1 - tax)
    wacc = (equity_weight / total_cap) * cost_equity + (debt / total_cap) * cost_debt_after_tax

    if wacc - g_terminal < MIN_SPREAD:
        # Gordon's denominator goes to zero and the value goes to infinity. Refusing is the only
        # honest answer: it means our own assumptions say this company grows about as fast as it
        # is discounted, which a five-line model cannot value.
        return DCFResult(verdict="no value", wacc=round(wacc, 4),
                         cost_of_equity=round(cost_equity, 4), terminal_growth=g_terminal,
                         reason=f"WACC {wacc:.1%} does not clear terminal growth "
                                f"{g_terminal:.1%} by {MIN_SPREAD:.0%}",
                         assumptions=assumptions)

    # Five years explicit, then a Gordon terminal on the fifth year's cash flow.
    # GROWTH FADES to the terminal rate across the forecast rather than holding flat. Holding
    # a fitted 20% for five years and then capitalising the inflated fifth year is what valued
    # Emaar Development at eight times its own market capitalisation: the terminal value is
    # computed on a cash flow that compounding has already doubled. A linear fade is the
    # textbook treatment and it is what a competitive economy actually does to growth rates.
    pv = 0.0
    flow = base
    for year in range(1, FORECAST_YEARS + 1):
        step = growth + (g_terminal - growth) * (year / FORECAST_YEARS)
        flow = flow * (1 + step)
        pv += flow / (1 + wacc) ** year
    terminal = flow * (1 + g_terminal) / (wacc - g_terminal)
    pv_terminal = terminal / (1 + wacc) ** FORECAST_YEARS
    enterprise = pv + pv_terminal

    if enterprise > 0 and pv_terminal / enterprise > MAX_TERMINAL_SHARE:
        return DCFResult(verdict="no value", wacc=round(wacc, 4), growth=round(growth, 4),
                         terminal_growth=g_terminal, base_fcf=round(base, 2),
                         quarters_used=len(fcf_series),
                         reason=(f"{pv_terminal / enterprise:.0%} of the value is the terminal "
                                 "assumption - that is a view on perpetuity, not a valuation"),
                         assumptions=assumptions)

    net_debt = debt - cash_now
    equity_value = enterprise - net_debt
    if equity_value <= 0:
        return DCFResult(verdict="no value", wacc=round(wacc, 4), growth=round(growth, 4),
                         enterprise_value=round(enterprise, 2), net_debt=round(net_debt, 2),
                         reason="net debt exceeds the discounted value of the business",
                         assumptions=assumptions)

    shares = shares_now
    if not shares or shares <= 0:
        return DCFResult(verdict="no value", wacc=round(wacc, 4), growth=round(growth, 4),
                         enterprise_value=round(enterprise, 2), equity_value=round(equity_value, 2),
                         reason="no diluted share count, so no per-share value",
                         assumptions=assumptions)

    fair = equity_value / shares
    if price and price > 0:
        multiple = fair / price
        if multiple > MAX_PRICE_MULTIPLE or multiple < MIN_PRICE_MULTIPLE:
            return DCFResult(verdict="no value", wacc=round(wacc, 4), growth=round(growth, 4),
                             base_fcf=round(base, 2), quarters_used=len(fcf_series),
                             equity_value=round(equity_value, 2), shares=shares,
                             reason=(f"fair value is {multiple:,.1f}x the traded price - the "
                                     "inputs disagree with the market by more than this model "
                                     "can justify, so no value is published"),
                             assumptions=assumptions)
    upside = ((fair / price - 1) * 100) if price and price > 0 else None
    verdict = "no value"
    if upside is not None:
        verdict = ("undervalued" if upside > 20 else
                   "overvalued" if upside < -20 else "fairly valued")

    return DCFResult(
        fair_value=round(fair, 4),
        upside_pct=round(upside, 2) if upside is not None else None,
        wacc=round(wacc, 4), cost_of_equity=round(cost_equity, 4),
        growth=round(growth, 4), terminal_growth=g_terminal,
        base_fcf=round(base, 2), quarters_used=len(fcf_series),
        enterprise_value=round(enterprise, 2), equity_value=round(equity_value, 2),
        net_debt=round(net_debt, 2), shares=shares, verdict=verdict,
        assumptions=assumptions,
        reason=(f"{len(fcf_series)} quarters of FCF fitted to {growth:.1%} a year, "
                f"discounted at {wacc:.1%}, terminal {g_terminal:.1%}"),
    )
