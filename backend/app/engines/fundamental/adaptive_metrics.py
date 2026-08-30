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
    BANK,
    COUNTRIES,
    DEFAULT_COUNTRY,
    GOOD,
    INAPPLICABLE,
    INSURER,
    Metric,
    _at,
    _cagr,
    _f,
    _series,
    prorata,
    prorata_change,
)

Q3Y, Q5Y = 12, 20

# Anchors for the metrics the specification scores absolutely. Interest cover, the liquidity
# ratios and cash conversion mean the same thing in Karachi as in New York - a company either
# covers its interest or it does not - so unlike growth, margins, leverage and returns these
# are NOT country-adjusted. Saying so is the point: an unadjusted threshold should be a
# decision, not an oversight.
COVER_BAD, COVER_AVG, COVER_GOOD = 1.5, 3.0, 8.0
CR_BAD, CR_AVG, CR_GOOD = 0.8, 1.2, 2.0
QR_BAD, QR_AVG, QR_GOOD = 0.5, 1.0, 1.5
CFO_NI_BAD, CFO_NI_AVG, CFO_NI_GOOD = 0.6, 1.0, 1.2


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


def _latest_all(*series: list[float | None]) -> int | None:
    """Newest index at which EVERY one of these series reports a value, or None.

    This is what stops a ratio being built out of two different periods. It also stops a
    metric being discarded because the newest column happens to be blank: across our store the
    newest TTM column is null for 19% of inventory and 10% of current assets, while no company
    has a field that is null in every column. Those are reporting lags, and reading index 0
    alone silently dropped a third of Indian companies out of the liquidity metrics.
    """
    if not series:
        return None
    n = min((len(s) for s in series), default=0)
    for i in range(n):
        if all(s[i] is not None for s in series):
            return i
    return None


def _age_note(idx: int | None) -> str:
    """Say so when a metric was not read from the newest period. Silence here would let a
    figure two years stale look exactly as current as one filed last quarter."""
    if not idx:
        return ""
    years = idx / 4.0
    if years >= 1:
        return f"latest reported is {years:.1f}y old"
    return f"latest reported is {idx} quarter{'s' if idx > 1 else ''} back"


def _margin_anchors(median: float | None, avg_abs: float, good_abs: float,
                    label: str) -> tuple[float, float, float, str]:
    """Anchors for a margin, against the INDUSTRY median where we have one.

    At the industry median a company is average and scores 3; the spread that earns a 5 is
    half the median again, floored at three percentage points so a razor-thin industry does
    not get an absurdly tight band (a 0.4% median would otherwise make 0.6% "good").
    """
    if median is None:
        return (avg_abs - (good_abs - avg_abs), avg_abs, good_abs,
                f"{label} (no industry median)")
    spread = max(abs(median) * 0.5, 0.03)
    return median - spread, median, median + spread, f"industry median {median:.1%}"


def build_metrics(inc: list[dict], bal: list[dict], cf: list[dict],
                  region: str, model: str, market: dict | None = None,
                  peers: dict | None = None) -> list[Metric]:
    """The fifteen metrics of the matrix, and nothing else.

    `market` is unused - the matrix scores the BUSINESS, and what the market will pay for it
    is the valuation engine's question. It stays in the signature because callers pass it.
    """
    # A bank is not an operating company with missing data - it is a different kind of
    # business, and it gets its own matrix rather than this one with eleven holes in it.
    if model in (BANK, INSURER):
        from app.engines.fundamental.financial import build_financial_metrics

        return build_financial_metrics(inc, bal, region, model)

    c = COUNTRIES.get(region, DEFAULT_COUNTRY)
    na = INAPPLICABLE.get(model, set())
    peers = peers or {}

    rev = _series(inc, "revenue")
    gp = _series(inc, "gross_profit")
    op = _series(inc, "operating_income")
    net = _series(inc, "net_income")
    interest = _series(inc, "interest_expense")
    pbt = _series(inc, "income_before_tax")
    tax = _series(inc, "income_tax_expense")

    equity = _series(bal, "total_equity")
    debt = _series(bal, "total_debt")
    cash = _series(bal, "cash_and_equivalents")
    cur_a = _series(bal, "current_assets")
    cur_l = _series(bal, "current_liabilities")
    inv = _series(bal, "inventory")

    cfo = _series(cf, "operating_cash_flow")
    capex = _series(cf, "capital_expenditure")

    out: list[Metric] = []

    def add(key, category, label, value=None, score=None, benchmark="", note=""):
        if key in na:
            out.append(Metric(key, category, label, value, None, None, None, benchmark,
                              "N/A - not economically meaningful for this model",
                              na_model=True))
        else:
            out.append(Metric(key, category, label, value, None, None, score, benchmark,
                              note or ("" if score is not None else "no data")))

    # ------------------------------------------------------------------ 1-3  growth
    gb, ga = c.growth_good, c.growth_avg
    bench_g = f"{ga:.0%} avg / {gb:.0%} good ({c.name})"
    for key, label, vals in (("sales_growth", "Revenue Growth", rev),
                             ("op_growth", "Operating Profit Growth", op),
                             ("net_growth", "Net Profit Growth", net)):
        v = _best_cagr(vals)
        # Profit may legitimately have no CAGR because the series crossed zero. That is a
        # finding - falling profit scores BAD - not an absence of one.
        floor = 0.0 if key == "net_growth" else ga - (gb - ga)
        score_v = prorata(v, floor, ga, gb)
        if score_v is None:
            now, before = _at(vals, 0), _at(vals, min(Q3Y, max(0, len(vals) - 1)))
            if now is not None and before is not None and (now <= 0 < before or now <= 0):
                score_v = BAD
        add(key, "growth", label, v, score_v, bench_g)

    # ------------------------------------------------------------------ 4-6  margins
    for key, label, num, peer_key, avg_abs, good_abs, fb in (
        ("gross_margin", "Gross Margin", gp, "gross_margin", 0.25, 0.40,
         "25% avg / 40% good"),
        ("operating_margin", "Operating Margin", op, "operating_margin", 0.05, 0.12,
         "5% avg / 12% good"),
        ("net_margin", "Net Margin", net, "net_margin", 0.03, 0.08,
         "3% avg / 8% good"),
    ):
        idx = _latest_all(num, rev)
        value = None
        if idx is not None and (rev[idx] or 0) > 0:
            value = num[idx] / rev[idx]
        bad_a, avg_a, good_a, bench = _margin_anchors(_f(peers.get(peer_key)),
                                                      avg_abs, good_abs, fb)
        add(key, "margins", label, value, prorata(value, bad_a, avg_a, good_a), bench,
            _age_note(idx))

    # ------------------------------------------------------------------ 7  debt to equity
    idx = _latest_all(debt, equity)
    de = None
    if idx is not None and (equity[idx] or 0) > 0:
        de = debt[idx] / equity[idx]
    add("debt_to_equity", "leverage", "Debt to Equity", de,
        prorata(de, c.de_bad, c.de_avg, c.de_good),
        f"{c.name} exchange: {c.de_good:.2f} good / {c.de_avg:.2f} median / "
        f"{c.de_bad:.2f} weak", _age_note(idx))

    # ------------------------------------------------------------------ 10  interest cover
    idx = _latest_all(op, interest)
    cover = None
    if idx is not None:
        # THE MAGNITUDE, because the store signs interest expense NEGATIVE - 8,364 companies
        # against 150 positive. Testing `interest > 0` therefore almost never fired, every
        # company fell through to the "nothing to cover" default, and 98.3% of the universe
        # scored a perfect 5 on interest coverage. A metric that returns the same answer for
        # everyone is not a lenient metric, it is a broken one.
        burden = abs(interest[idx])
        # A company with no interest expense has nothing to cover, which is the good case and
        # not missing data.
        cover = op[idx] / burden if burden > 0 else COVER_GOOD
    add("interest_coverage", "leverage", "Interest Coverage", cover,
        prorata(cover, COVER_BAD, COVER_AVG, COVER_GOOD),
        f"{COVER_AVG:.0f}x avg / {COVER_GOOD:.0f}x good", _age_note(idx))

    # ------------------------------------------------------------------ 8  return on equity
    idx = _latest_all(net, equity)
    roe = None
    if idx is not None and (equity[idx] or 0) > 0:
        roe = net[idx] / equity[idx]
    add("roe", "returns", "Return on Equity", roe,
        prorata(roe, 0.0, c.roe_good * 0.5, c.roe_good),
        f"{c.roe_good * 0.5:.0%} avg / {c.roe_good:.0%} good ({c.name})", _age_note(idx))

    # ------------------------------------------------------------------ 9  ROIC
    # Against the LOCAL cost of capital, not a fixed hurdle: 10% ROIC destroys value in
    # Pakistan, where the risk-free rate alone is 11.5%, and creates it in the United States.
    idx = _latest_all(op, equity, debt)
    roic = None
    if idx is not None:
        eff = _ratio(_at(tax, idx), _at(pbt, idx))
        if eff is None or not 0.0 <= eff <= 0.5:
            eff = c.statutory_tax
        nopat = op[idx] * (1.0 - eff)
        invested = debt[idx] + equity[idx] - (_at(cash, idx) or 0.0)
        if invested > 0:
            roic = nopat / invested
    roic_avg, roic_good = c.risk_free + 0.02, c.risk_free + 0.06
    add("roic", "returns", "Return on Invested Capital", roic,
        prorata(roic, max(0.0, c.risk_free - 0.02), roic_avg, roic_good),
        f"beats the {c.risk_free:.1%} local risk-free rate: {roic_avg:.0%} avg / "
        f"{roic_good:.0%} good", _age_note(idx))

    # ------------------------------------------------------------------ 11  current ratio
    idx = _latest_all(cur_a, cur_l)
    cr = None
    if idx is not None and (cur_l[idx] or 0) > 0:
        cr = cur_a[idx] / cur_l[idx]
    add("current_ratio", "liquidity", "Current Ratio", cr,
        prorata(cr, CR_BAD, CR_AVG, CR_GOOD), f"{CR_AVG} avg / {CR_GOOD} good",
        _age_note(idx))

    # ------------------------------------------------------------------ 12  quick ratio
    # Inventory is ALWAYS a balance-sheet line, so a company reporting none genuinely holds
    # none - services and financials - and its quick ratio is its current ratio. But a company
    # that reports inventory in SOME period and not the newest has stock we simply have not
    # received the figure for: netting off nothing there would flatter it. So a reporter is
    # measured at the newest period where all three figures exist, and only a company that
    # never reports inventory at all is treated as holding none.
    reports_inventory = any(v is not None for v in inv)
    if reports_inventory:
        idx = _latest_all(cur_a, cur_l, inv)
        qr = None
        if idx is not None and (cur_l[idx] or 0) > 0:
            qr = (cur_a[idx] - inv[idx]) / cur_l[idx]
        note = _age_note(idx)
    else:
        idx = _latest_all(cur_a, cur_l)
        qr = None
        if idx is not None and (cur_l[idx] or 0) > 0:
            qr = cur_a[idx] / cur_l[idx]
        note = "; ".join(x for x in ("no inventory reported - equals the current ratio",
                                     _age_note(idx)) if x)
    add("quick_ratio", "liquidity", "Quick Ratio", qr,
        prorata(qr, QR_BAD, QR_AVG, QR_GOOD), f"{QR_AVG} avg / {QR_GOOD} good", note)

    # ------------------------------------------------------------------ 13  CFO vs net income
    idx = _latest_all(cfo, net)
    ratio = None
    score_q = None
    if idx is not None:
        n_i, o_f = net[idx], cfo[idx]
        if n_i > 0:
            ratio = o_f / n_i
            score_q = prorata(ratio, CFO_NI_BAD, CFO_NI_AVG, CFO_NI_GOOD)
        else:
            # No ratio against a loss, but the comparison still has an answer: cash coming in
            # while the income statement shows a loss is the good case, and it is the case a
            # ratio would have thrown away as undefined.
            score_q = GOOD if o_f > 0 else BAD
    add("cfo_vs_net_income", "cash_flow", "Operating Cash Flow vs Net Income", ratio, score_q,
        f"{CFO_NI_AVG:.1f}x avg / {CFO_NI_GOOD:.1f}x good", _age_note(idx))

    # ------------------------------------------------------------------ 14-15  cash flow sign
    idx = _latest_all(cfo)
    v_cfo = None if idx is None else cfo[idx]
    add("operating_cash_flow", "cash_flow", "Operating Cash Flow", v_cfo,
        None if v_cfo is None else (GOOD if v_cfo > 0 else BAD),
        "positive / negative", _age_note(idx))

    idx = _latest_all(cfo, capex)
    fcf = None if idx is None else cfo[idx] - abs(capex[idx])
    add("free_cash_flow", "cash_flow", "Free Cash Flow", fcf,
        None if fcf is None else (GOOD if fcf > 0 else BAD),
        "positive / negative", _age_note(idx))

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
    # Guard EVERY statement, not just the income one. The three lists are independent and can
    # each be empty or short - this function crashed the whole universe refresh twice, first on
    # a company with a shorter cash-flow history and then on one with no cash-flow rows at all.
    # Checking the list you are about to index is the fix; checking a different list is not.
    if len(inc) < 5 or not bal or not cf:
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

    cfo0, net0 = _f(cf[0].get("operating_cash_flow")), _f(inc[0].get("net_income"))  # guarded above
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
