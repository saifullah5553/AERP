"""Metric computation for the adaptive fundamental engine.

Split from `adaptive.py` so the thresholds and the arithmetic can be read separately: the
first file is the judgement (what counts as good, and where that differs by country), this one
is the measurement.

Every metric is computed from the quarterly-TTM store and nothing else. Each stored row is
already a full trailing year, so index 4 is one year ago, 12 is three years ago and 20 is five
years ago - a 3-year average is the mean of the last twelve TTM observations, not of three
annual filings.
"""

from __future__ import annotations

from app.engines.fundamental.adaptive import (
    AVERAGE,
    BAD,
    COUNTRIES,
    DEFAULT_COUNTRY,
    GOOD,
    INAPPLICABLE,
    Metric,
    _at,
    _avg,
    _cagr,
    _f,
    _series,
    prorata,
    prorata_change,
)

Q3Y, Q5Y = 12, 20


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _ratio_series(num: list[float | None], den: list[float | None]) -> list[float | None]:
    return [_ratio(n, d) for n, d in zip(num, den, strict=False)]


def _best_cagr(vals: list[float | None]) -> float | None:
    """CAGR over the longest span the history actually supports.

    Three years is the preferred window, but insisting on it means a company with two years of
    filings gets NO growth score at all - and because the weight then leaves the total, a firm
    growing 35% scored identically to one growing 2%. Growth was silently absent rather than
    visibly weak. Falls back through 3y, 1y, then whatever span exists.
    """
    for span in (Q3Y, 8, 4):
        out = _cagr(vals, span)
        if out is not None:
            return out
    last = len(vals) - 1
    return _cagr(vals, last) if last >= 1 else None


def build_metrics(inc: list[dict], bal: list[dict], cf: list[dict],
                  region: str, model: str, market: dict | None,
                  peers: dict | None = None) -> list[Metric]:
    """Every metric the specification asks for that our data can actually support."""
    c = COUNTRIES.get(region, DEFAULT_COUNTRY)
    na = INAPPLICABLE.get(model, set())
    market = market or {}
    price = _f(market.get("price"))
    mcap = _f(market.get("market_cap"))

    rev = _series(inc, "revenue")
    op = _series(inc, "operating_income")
    net = _series(inc, "net_income")
    cogs = _series(inc, "cost_of_revenue")
    tax = _series(inc, "income_tax_expense")
    pbt = _series(inc, "income_before_tax")
    interest = _series(inc, "interest_expense")
    ebitda = _series(inc, "ebitda")
    shares = _series(inc, "weighted_shares")

    assets = _series(bal, "total_assets")
    equity = _series(bal, "total_equity")
    debt = _series(bal, "total_debt")
    cash = _series(bal, "cash_and_equivalents")
    cur_a = _series(bal, "current_assets")
    cur_l = _series(bal, "current_liabilities")
    inv = _series(bal, "inventory")
    recv = _series(bal, "receivables")
    payable = _series(bal, "accounts_payable")

    cfo = _series(cf, "operating_cash_flow")
    capex = _series(cf, "capital_expenditure")
    dvd = _series(cf, "dividends_paid")
    net_chg = _series(cf, "net_change_in_cash")

    # EPS is DERIVED from net income and diluted shares of the SAME period. The reported EPS
    # line publishes late, so reading it directly pairs one period of earnings with another
    # period of everything else.
    eps = [_ratio(n, s) for n, s in zip(net, shares, strict=False)]
    fcf = [(o - abs(x)) if (o is not None and x is not None) else None
           for o, x in zip(cfo, capex, strict=False)]

    out: list[Metric] = []

    def add(key, category, label, value=None, avg3=None, avg5=None, score=None,
            benchmark="", note=""):
        if key in na:
            out.append(Metric(key, category, label, value, avg3, avg5, None, benchmark,
                              "N/A - not economically meaningful for this model",
                              na_model=True))
        else:
            out.append(Metric(key, category, label, value, avg3, avg5, score, benchmark,
                              note or ("" if score is not None else "no data")))

    # ---------------------------------------------------------------- growth
    gb, ga = c.growth_good, c.growth_avg
    bench_g = f"{ga:.0%} avg / {gb:.0%} good ({c.name})"
    for key, label, vals in (("sales_cagr", "Sales CAGR", rev),
                             ("op_cagr", "Operating Profit CAGR", op),
                             ("net_cagr", "Net Profit CAGR", net)):
        v = _best_cagr(vals)
        floor = 0.0 if key == "net_cagr" else ga - (gb - ga)
        score_v = prorata(v, floor, ga, gb)
        if score_v is None:
            # No CAGR because the series turned negative. The specification scores that BAD
            # ("<0% = BAD"), and it is a real finding - not an absence of one.
            now, before = _at(vals, 0), _at(vals, min(Q3Y, max(0, len(vals) - 1)))
            if now is not None and before is not None and (now <= 0 < before or now <= 0):
                score_v = BAD
        add(key, "growth", label, v, None, None, score_v, bench_g)

    e3, e5 = _avg(eps, Q3Y), _avg(eps, Q5Y)
    add("eps_trend", "growth", "EPS (3Y avg vs 5Y avg)", _at(eps, 0), e3, e5,
        prorata_change(e3, e5), "3Y average above 5Y average")

    # ---------------------------------------------------------------- stability
    op_m = _ratio_series(op, rev)
    net_m = _ratio_series(net, rev)
    sector_om = _f((peers or {}).get("operating_margin"))
    if sector_om is not None:
        om_good, om_avg = sector_om * 1.25, sector_om * 0.75
        om_bench = f"sector median {sector_om:.1%}"
    else:
        om_good, om_avg = 0.12, 0.05
        om_bench = "12% good / 5% avg (Pakistan baseline)"
    add("operating_margin", "stability", "Operating Margin", _at(op_m, 0),
        _avg(op_m, Q3Y), _avg(op_m, Q5Y),
        prorata(_at(op_m, 0), om_avg - (om_good - om_avg), om_avg, om_good), om_bench)

    add("net_margin", "stability", "Net Margin", _at(net_m, 0),
        _avg(net_m, Q3Y), _avg(net_m, Q5Y),
        prorata(_at(net_m, 0), -0.02, 0.03, 0.08), "8% good / 3% avg")

    eff_tax = _ratio(_at(tax, 0), _at(pbt, 0))
    # Scored by DISTANCE from the statutory rate: a rate far below it is usually temporary
    # (credits, holidays, loss utilisation) and a rate far above it destroys earnings. Being
    # near the statutory rate is the sustainable case, so it anchors GOOD.
    tax_gap = None if eff_tax is None else abs(eff_tax - c.statutory_tax)
    add("tax_ratio", "stability", "Effective Tax Ratio", eff_tax, None, None,
        prorata(tax_gap, 0.25, 0.12, 0.03),
        f"near {c.statutory_tax:.0%} statutory ({c.name})")

    icov = _ratio(_at(op, 0), _at(interest, 0))
    add("interest_coverage", "stability", "Interest Coverage", icov, None, None,
        prorata(icov, 1.0, 2.5, 5.0), "5x good / 2.5x avg")

    de = _ratio(_at(debt, 0), _at(equity, 0))
    add("debt_to_equity", "stability", "Debt / Equity", de, None, None,
        prorata(de, 1.5, 1.0, 0.5), "0.5 good / 1.0 avg")

    d3, d5 = _avg(debt, Q3Y), _avg(debt, Q5Y)
    add("total_debt", "stability", "Total Debt (3Y vs 5Y)", _at(debt, 0), d3, d5,
        prorata_change(d3, d5, lower_is_better=True), "3Y average below 5Y average")

    cr = _ratio(_at(cur_a, 0), _at(cur_l, 0))
    add("current_ratio", "stability", "Current Ratio", cr, None, None,
        prorata(cr, 0.6, 0.8, 1.5), "1.5 good / 0.8 avg")

    c3, c5 = _avg(cfo, Q3Y), _avg(cfo, Q5Y)
    add("cfo_trend", "stability", "CFO (3Y vs 5Y)", _at(cfo, 0), c3, c5,
        prorata_change(c3, c5), "3Y average above 5Y average")

    nc = _at(net_chg, 0)
    # Scaled by revenue so a large company is not flattered by a large absolute number.
    nc_scaled = _ratio(nc, _at(rev, 0))
    add("net_change_cash", "stability", "Net Change in Cash", nc, None, None,
        prorata(nc_scaled, -0.05, 0.0, 0.05), "positive, scaled by revenue")

    cfo_pat = _ratio(_at(cfo, 0), _at(net, 0))
    add("cfo_vs_pat", "stability", "CFO vs PAT", cfo_pat, None, None,
        prorata(cfo_pat, 0.5, 1.0, 1.5), "CFO above PAT")

    net_fa = [(a - ca) if (a is not None and ca is not None) else None
              for a, ca in zip(assets, cur_a, strict=False)]
    fat = _ratio_series(rev, net_fa)
    f3, f5 = _avg(fat, Q3Y), _avg(fat, Q5Y)
    add("fixed_asset_turnover", "stability", "Net Fixed Asset Turnover", _at(fat, 0), f3, f5,
        prorata_change(f3, f5), "3Y average above 5Y average")

    roe_s = _ratio_series(net, equity)
    add("roe", "stability", "ROE", _at(roe_s, 0), _avg(roe_s, Q3Y), _avg(roe_s, Q5Y),
        prorata(_at(roe_s, 0), 0.0, c.roe_good * 0.6, c.roe_good),
        f"{c.roe_good:.0%} good ({c.name})")

    # ---------------------------------------------------------------- valuation
    eps0 = _at(eps, 0)
    # A LOSS-MAKING company does not have an unavailable P/E - it has a bad one, and the
    # difference decides whether it is scored at all. Treating negative earnings as missing
    # data left 500+ companies below the coverage gate and therefore UNRATED, which reads on
    # the screener exactly like "we have no information" rather than "this company loses
    # money". The same applies to earnings yield, Graham and EV/EBITDA below.
    loss_making = eps0 is not None and eps0 <= 0
    pe = _ratio(price, eps0) if (price and eps0 and eps0 > 0) else None
    add("pe", "valuation", "P/E", pe, None, None,
        BAD if (loss_making and price) else prorata(pe, c.pe_avg * 1.6, c.pe_avg, c.pe_good),
        f"<{c.pe_good:g} good / <{c.pe_avg:g} avg ({c.name})",
        "negative earnings" if loss_making else "")

    growth_for_peg = _cagr(net, Q3Y)
    peg = None
    if pe is not None and growth_for_peg and growth_for_peg > 0.01:
        peg = pe / (growth_for_peg * 100.0)
    add("peg", "valuation", "PEG", peg, None, None, prorata(peg, 3.0, 1.5, 1.0),
        "<1 good; unreliable when growth is negative or erratic")

    ey = (1.0 / pe) if (pe and pe > 0) else None
    # Compared with the LOCAL risk-free rate, in the same currency and risk environment.
    add("earnings_yield", "valuation", "Earnings Yield", ey, None, None,
        BAD if (loss_making and price)
        else prorata(ey, c.risk_free * 0.5, c.risk_free, c.risk_free * 1.6),
        f"vs {c.risk_free:.1%} local risk-free ({c.name})",
        "negative earnings yield" if loss_making else "")

    bvps = _ratio(_at(equity, 0), _at(shares, 0))
    pb = _ratio(price, bvps) if price else None
    add("pb", "valuation", "P/B", pb, None, None,
        prorata(pb, c.pb_good * 2.5, c.pb_good * 1.5, c.pb_good),
        f"<{c.pb_good:g} good ({c.name})")

    graham = (pe * pb) if (pe is not None and pb is not None) else None
    add("graham", "valuation", "Graham (P/E x P/B)", graham, None, None,
        BAD if (loss_making and pb is not None)
        else prorata(graham, 60.0, 40.0, 22.5), "<22.5 good; secondary indicator only")

    ps = _ratio(mcap, _at(rev, 0)) if mcap else None
    add("ps", "valuation", "P/S", ps, None, None,
        prorata(ps, c.ps_avg * 1.8, c.ps_avg, c.ps_good),
        f"<{c.ps_good:g} good / <{c.ps_avg:g} avg ({c.name})")

    dvd0 = _at(dvd, 0)
    # No dividend line is a zero yield, not an unknown one - the company paid nothing. Only a
    # missing MARKET CAP makes the yield genuinely unmeasurable.
    dvd_yield = (abs(dvd0) / mcap if dvd0 is not None else 0.0) if mcap else None
    add("dividend_yield", "valuation", "Dividend Yield", dvd_yield, None, None,
        prorata(dvd_yield, 0.0, c.div_good * 0.5, c.div_good),
        f"{c.div_good:.1%} good ({c.name}, vs local bonds)")

    ev = None
    if mcap is not None:
        ev = mcap + (_at(debt, 0) or 0.0) - (_at(cash, 0) or 0.0)
    ebitda0 = _at(ebitda, 0)
    ev_ebitda = _ratio(ev, ebitda0) if (ebitda0 or 0) > 0 else None
    add("ev_ebitda", "valuation", "EV / EBITDA", ev_ebitda, None, None,
        BAD if (ev is not None and ebitda0 is not None and ebitda0 <= 0)
        else prorata(ev_ebitda, c.ev_ebitda_good * 2.2, c.ev_ebitda_good * 1.4,
                     c.ev_ebitda_good),
        f"<{c.ev_ebitda_good:g} good ({c.name})",
        "negative EBITDA" if (ebitda0 is not None and ebitda0 <= 0) else "")

    # ---------------------------------------------------------------- working capital
    inv_turn = _ratio_series([abs(x) if x is not None else None for x in cogs], inv)
    i3, i5 = _avg(inv_turn, Q3Y), _avg(inv_turn, Q5Y)
    add("inventory_turnover", "working_capital", "Inventory Turnover", _at(inv_turn, 0), i3, i5,
        prorata_change(i3, i5), "3Y average above 5Y average")

    dso_s = [(_ratio(r, rv) or 0) * 365 if (r is not None and rv) else None
             for r, rv in zip(recv, rev, strict=False)]
    s3, s5 = _avg(dso_s, Q3Y), _avg(dso_s, Q5Y)
    add("dso", "working_capital", "Days Receivable", _at(dso_s, 0), s3, s5,
        prorata_change(s3, s5, lower_is_better=True), "3Y average below 5Y average")

    dio_s = [(_ratio(iv, abs(cg)) or 0) * 365 if (iv is not None and cg) else None
             for iv, cg in zip(inv, cogs, strict=False)]
    o3, o5 = _avg(dio_s, Q3Y), _avg(dio_s, Q5Y)
    add("dio", "working_capital", "Days Inventory", _at(dio_s, 0), o3, o5,
        prorata_change(o3, o5, lower_is_better=True), "3Y average below 5Y average")

    dpo_s = [(_ratio(p, abs(cg)) or 0) * 365 if (p is not None and cg) else None
             for p, cg in zip(payable, cogs, strict=False)]
    p3, p5 = _avg(dpo_s, Q3Y), _avg(dpo_s, Q5Y)
    add("dpo", "working_capital", "Days Payable", _at(dpo_s, 0), p3, p5,
        prorata_change(p3, p5), "3Y average above 5Y average")

    ccc_s = [((a or 0) + (b or 0) - (d or 0)) if None not in (a, b, d) else None
             for a, b, d in zip(dso_s, dio_s, dpo_s, strict=False)]
    x3, x5 = _avg(ccc_s, Q3Y), _avg(ccc_s, Q5Y)
    add("ccc", "working_capital", "Cash Conversion Cycle", _at(ccc_s, 0), x3, x5,
        prorata_change(x3, x5, lower_is_better=True), "3Y average below 5Y average")

    # ---------------------------------------------------------------- cash flow
    fcfps = _ratio_series(fcf, shares)
    q3, q5 = _avg(fcfps, Q3Y), _avg(fcfps, Q5Y)
    add("fcf_per_share", "cash_flow", "FCF per Share", _at(fcfps, 0), q3, q5,
        prorata_change(q3, q5), "3Y average above 5Y average")

    fcf_m = _ratio_series(fcf, rev)
    add("fcf_margin", "cash_flow", "FCF Margin", _at(fcf_m, 0),
        _avg(fcf_m, Q3Y), _avg(fcf_m, Q5Y),
        prorata(_at(fcf_m, 0), -0.05, 0.05, 0.10), "10% good")

    fcf_cfo = _ratio_series(fcf, cfo)
    add("fcf_to_cfo", "cash_flow", "FCF / CFO", _at(fcf_cfo, 0),
        _avg(fcf_cfo, Q3Y), _avg(fcf_cfo, Q5Y),
        prorata(_at(fcf_cfo, 0), 0.0, 0.4, 0.7), "high and stable conversion")

    invested = None
    d0, e0, c0 = _at(debt, 0), _at(equity, 0), _at(cash, 0)
    if d0 is not None and e0 is not None:
        invested = d0 + e0 - (c0 or 0.0)
    croic = _ratio(_at(fcf, 0), invested)
    add("croic", "cash_flow", "CROIC", croic, None, None,
        prorata(croic, 0.03, 0.08, 0.13), "13% good / 8% avg")

    return out


def piotroski_score(inc: list[dict], bal: list[dict], cf: list[dict]) -> int | None:
    """The standard nine factors, current TTM against the TTM one year earlier."""
    if len(inc) < 5 or len(bal) < 5 or len(cf) < 5:
        return None
    n0, n1 = _f(inc[0].get("net_income")), _f(inc[4].get("net_income"))
    a0, a1 = _f(bal[0].get("total_assets")), _f(bal[4].get("total_assets"))
    c0 = _f(cf[0].get("operating_cash_flow"))
    ltd0, ltd1 = _f(bal[0].get("long_term_debt")), _f(bal[4].get("long_term_debt"))
    ca0, cl0 = _f(bal[0].get("current_assets")), _f(bal[0].get("current_liabilities"))
    ca1, cl1 = _f(bal[4].get("current_assets")), _f(bal[4].get("current_liabilities"))
    sh0, sh1 = _f(inc[0].get("weighted_shares")), _f(inc[4].get("weighted_shares"))
    g0, g1 = _f(inc[0].get("gross_profit")), _f(inc[4].get("gross_profit"))
    r0, r1 = _f(inc[0].get("revenue")), _f(inc[4].get("revenue"))

    pts = 0
    if n0 is not None and n0 > 0:
        pts += 1
    roa0 = _ratio(n0, a0)
    roa1 = _ratio(n1, a1)
    if roa0 is not None and roa0 > 0:
        pts += 1
    if c0 is not None and c0 > 0:
        pts += 1
    if c0 is not None and n0 is not None and c0 > n0:
        pts += 1
    lev0, lev1 = _ratio(ltd0, a0), _ratio(ltd1, a1)
    if lev0 is not None and lev1 is not None and lev0 <= lev1:
        pts += 1
    cr0, cr1 = _ratio(ca0, cl0), _ratio(ca1, cl1)
    if cr0 is not None and cr1 is not None and cr0 > cr1:
        pts += 1
    if sh0 is not None and sh1 is not None and sh0 <= sh1 * 1.02:
        pts += 1
    gm0, gm1 = _ratio(g0, r0), _ratio(g1, r1)
    if gm0 is not None and gm1 is not None and gm0 > gm1:
        pts += 1
    at0, at1 = _ratio(r0, a0), _ratio(r1, a1)
    if at0 is not None and at1 is not None and at0 > at1:
        pts += 1
    # roa1 is computed for symmetry with the classic formulation; it is not itself a point.
    _ = roa1
    return pts


def accounting_flags(inc: list[dict], bal: list[dict], cf: list[dict]) -> list[str]:
    """Section 13. These do not move the mechanical score; they qualify the conclusion."""
    flags: list[str] = []
    if len(inc) < 5:
        return flags

    def yoy(rows, key):
        # Guarded per-statement, not by the length of `inc`. The three statements can differ
        # in length - a company can hold five income periods and two cash-flow ones - and
        # taking the year-ago row on trust crashed the whole universe refresh on the first
        # company where they disagreed.
        if len(rows) < 5:
            return None
        a, b = _f(rows[0].get(key)), _f(rows[4].get(key))
        if a is None or b is None or b == 0:
            return None
        return (a - b) / abs(b)

    rev_g = yoy(inc, "revenue")
    net_g = yoy(inc, "net_income")
    cfo_g = yoy(cf, "operating_cash_flow")
    recv_g = yoy(bal, "receivables")
    inv_g = yoy(bal, "inventory")
    debt_g = yoy(bal, "total_debt")

    if rev_g is not None and cfo_g is not None and rev_g > 0.05 and cfo_g < -0.05:
        flags.append("revenue rising while operating cash flow falls")
    if net_g is not None and cfo_g is not None and net_g > 0.05 and cfo_g < -0.05:
        flags.append("profit rising while operating cash flow falls")
    if recv_g is not None and rev_g is not None and recv_g > rev_g + 0.15:
        flags.append("receivables growing materially faster than revenue")
    if inv_g is not None and rev_g is not None and inv_g > rev_g + 0.20:
        flags.append("inventory growing materially faster than revenue")
    if debt_g is not None and debt_g > 0.35:
        flags.append("total debt up more than a third year on year")

    cfo0, net0 = _f(cf[0].get("operating_cash_flow")), _f(inc[0].get("net_income"))
    if cfo0 is not None and net0 is not None and net0 > 0 and cfo0 < net0 * 0.5:
        flags.append("operating cash flow below half of reported profit")

    op0, pbt0 = _f(inc[0].get("operating_income")), _f(inc[0].get("income_before_tax"))
    if op0 is not None and pbt0 is not None and op0 > 0 and pbt0 > op0 * 1.5:
        flags.append("pre-tax profit far above operating profit - large non-operating income")

    sh0, sh1 = _f(inc[0].get("weighted_shares")), _f(inc[4].get("weighted_shares"))
    if sh0 is not None and sh1 is not None and sh1 > 0 and sh0 > sh1 * 1.10:
        flags.append("share count up more than 10% - dilution")

    return flags


def risk_from_flags(flags: list[str]) -> str:
    if len(flags) >= 3:
        return "HIGH"
    if len(flags) >= 1:
        return "MEDIUM"
    return "LOW"


__all__ = ["build_metrics", "piotroski_score", "accounting_flags", "risk_from_flags",
           "AVERAGE", "BAD", "GOOD", "Metric", "prorata", "prorata_change"]
