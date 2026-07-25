"""Pabrai Checklist Score — an independent business-quality + value model.

A 0–100 score measuring how closely a company aligns with the principles commonly
associated with Mohnish Pabrai's value investing (understandable business, moat, high
returns on capital, conservative balance sheet, consistent growth, strong cash flow,
honest capital allocation, stable margins, owner earnings, predictability, conservative
accounting, attractive valuation, management quality).

It is NOT a buy/sell call and does NOT feed the composite. Every metric is judged
through the Market Benchmark Engine (country + industry + company-history), so the same
bar is never applied across different markets. Each item is fully explained; items with
no data drop out and the remaining weights renormalise (coverage-aware), so a company is
never penalised for data we simply don't have.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.benchmark.engine import score_metric
from app.models.enums import StatementPeriod
from app.models.fundamentals import (
    CashFlowStatement,
    FinancialRatios,
    IncomeStatement,
)
from app.models.market import Security
from app.models.scoring import Score

log = get_logger(__name__)

# Item weights (sum to 100). Configurable.
WEIGHTS = {
    "understandable": 5, "moat": 10, "return_on_capital": 10, "balance_sheet": 10,
    "earnings_growth": 10, "free_cash_flow": 10, "capital_allocation": 10,
    "stable_margins": 5, "owner_earnings": 5, "predictable": 5,
    "conservative_accounting": 5, "valuation": 10, "management": 5,
}

# Rough business-simplicity by sector keyword (qualitative proxy, 0..1).
_SIMPLICITY = [
    (("bank", "insurance", "financ", "modaraba"), 0.5),
    (("cement", "fertil", "food", "consumer", "utilit", "power", "textile",
      "oil & gas marketing", "tobacco", "beverage", "retail"), 0.9),
    (("pharma", "chemical", "engineering", "auto", "steel", "paper", "glass"), 0.75),
    (("technology", "software", "communication", "media"), 0.6),
    (("oil & gas", "exploration", "refiner", "mining", "materials"), 0.65),
]
_METRICS_FOR_MEDIAN = [
    "roe", "roic", "net_margin", "operating_margin", "gross_margin", "debt_to_equity",
    "interest_coverage", "revenue_cagr", "eps_cagr", "fcf_margin", "pe", "ev_ebitda",
    "pb", "peg", "earnings_yield", "fcf_yield",
]


@dataclass(slots=True)
class Item:
    key: str
    name: str
    weight: int
    score: float | None                    # 0..1
    metric: str = ""
    benchmark: str = ""
    reason: str = ""
    positives: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    available: bool = True


def _f(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _series(rows, attr) -> list[float]:
    return [x for x in (_f(getattr(r, attr, None)) for r in rows) if x is not None]


def _cv_stability(vals: list[float]) -> float | None:
    """Stability 0..1 from coefficient of variation (lower volatility → higher)."""
    clean = [v for v in vals if v is not None]
    if len(clean) < 3:
        return None
    mean = statistics.fmean(clean)
    if mean == 0:
        return None
    cv = statistics.pstdev(clean) / abs(mean)
    return max(0.0, min(1.0, 1.0 - cv))


def _simplicity(sector: str | None, industry: str | None) -> float:
    hay = f"{sector or ''} {industry or ''}".lower()
    for keys, val in _SIMPLICITY:
        if any(k in hay for k in keys):
            return val
    return 0.6


def _derived_metrics(r: FinancialRatios | None) -> dict[str, float | None]:
    """Metric map in benchmark units from a ratios row (+ valuation yields)."""
    if r is None:
        return {}
    pe = _f(r.pe_ratio)
    ev = _f(r.ev_to_ebitda)
    m = {
        "roe": _f(r.roe), "roic": _f(r.roic), "net_margin": _f(r.net_margin),
        "operating_margin": _f(r.operating_margin), "gross_margin": _f(r.gross_margin),
        "debt_to_equity": _f(r.debt_to_equity), "interest_coverage": _f(r.interest_coverage),
        "current_ratio": _f(r.current_ratio), "revenue_cagr": _f(r.revenue_cagr_3y),
        "eps_cagr": _f(r.eps_cagr_3y), "fcf_margin": _f(r.fcf_margin),
        "pe": pe if pe and pe > 0 else None, "ev_ebitda": ev if ev and ev > 0 else None,
        "pb": _f(r.price_to_book), "peg": _f(r.peg_ratio),
        "dividend_yield": _f(r.dividend_yield),
    }
    m["earnings_yield"] = (1.0 / pe) if pe and pe > 0 else None
    return m


@dataclass(slots=True)
class _Ctx:
    medians: dict[str, dict[str, float]]  # sector_key → metric → median


def _sector_key(sector: str | None) -> str:
    return (sector or "—").strip().lower()


def build_context(db: Session) -> _Ctx:
    """Industry medians per metric, from the latest annual ratios across the universe."""
    rows = db.execute(
        select(FinancialRatios, Security.sector)
        .join(Security, FinancialRatios.security_id == Security.id)
        .where(FinancialRatios.period == StatementPeriod.ANNUAL)
    ).all()
    # keep the latest annual row per security
    latest: dict[int, tuple] = {}
    for fr, sector in rows:
        cur = latest.get(fr.security_id)
        if cur is None or fr.fiscal_date > cur[0].fiscal_date:
            latest[fr.security_id] = (fr, sector)

    buckets: dict[str, dict[str, list[float]]] = {}
    for fr, sector in latest.values():
        sk = _sector_key(sector)
        dm = _derived_metrics(fr)
        b = buckets.setdefault(sk, {})
        for k in _METRICS_FOR_MEDIAN:
            v = dm.get(k)
            if v is not None:
                b.setdefault(k, []).append(v)
    medians = {
        sk: {k: statistics.median(vs) for k, vs in mv.items() if vs}
        for sk, mv in buckets.items()
    }
    return _Ctx(medians=medians)


def _annual(db: Session, model, security_id: int, limit: int = 10) -> list:
    return list(db.scalars(
        select(model)
        .where(model.security_id == security_id, model.period == StatementPeriod.ANNUAL)
        .order_by(model.fiscal_date.desc())
        .limit(limit)
    ))


CATEGORIES = [
    (85, "Exceptional Compounder"), (70, "High-Quality Business"),
    (55, "Above-Average Business"), (40, "Average Business"), (0, "Below-Average Business"),
]


def category_for(score: float) -> str:
    for cutoff, label in CATEGORIES:
        if score >= cutoff:
            return label
    return "Below-Average Business"


def compute_for_security(db: Session, security: Security, ctx: _Ctx) -> tuple[float | None, dict]:
    ratios = _annual(db, FinancialRatios, security.id)
    incomes = _annual(db, IncomeStatement, security.id)
    cashflows = _annual(db, CashFlowStatement, security.id)
    latest = ratios[0] if ratios else None
    dm = _derived_metrics(latest)
    region = security.market.region.value if security.market else None
    sector, industry = security.sector, security.industry
    med = ctx.medians.get(_sector_key(sector), {})

    def sm(metric: str):
        return score_metric(
            metric, dm.get(metric), region, sector, industry,
            industry_median=med.get(metric),
            company_history=[_f(getattr(r, _RATIO_ATTR.get(metric, metric), None)) for r in ratios],
        )

    def pct(x: float | None) -> str:
        return "—" if x is None else f"{x * 100:.1f}%"

    items: list[Item] = []

    # 1. Understandable business (qualitative sector proxy)
    simp = _simplicity(sector, industry)
    items.append(Item(
        "understandable", "Understandable Business", WEIGHTS["understandable"], simp,
        metric=sector or "—", benchmark="sector complexity",
        reason=f"Business model complexity is judged from the sector ({sector or 'n/a'}); "
               f"simpler, transparent operations score higher.",
        positives=["Transparent, easy-to-follow business"] if simp >= 0.8 else [],
        negatives=["Business model is relatively complex to analyse"] if simp < 0.6 else [],
    ))

    # 2. Durable competitive advantage — ROE level + margin/ROE stability
    roe_s = sm("roe")
    nm_s = sm("net_margin")
    roe_stab = _cv_stability(_series(ratios, "roe"))
    nm_stab = _cv_stability(_series(ratios, "net_margin"))
    moat_parts = [x for x in (roe_s.score, nm_s.score, roe_stab, nm_stab) if x is not None]
    moat = statistics.fmean(moat_parts) if moat_parts else None
    items.append(Item(
        "moat", "Durable Competitive Advantage", WEIGHTS["moat"], moat,
        metric=f"ROE {pct(dm.get('roe'))}", benchmark="country+industry+history & stability",
        reason="Combines the level of returns (ROE) and margins with how stable they have "
               "been over time — persistent high returns signal a moat.",
        positives=(["Stable, high returns on equity"]
                   if (roe_stab or 0) > 0.7 and (roe_s.score or 0) > 0.6 else []),
        negatives=(["Volatile returns/margins suggest a weak moat"]
                   if (roe_stab or 1) < 0.5 else []),
    ))

    # 3. High return on capital — ROIC + ROE
    roic_s = sm("roic")
    parts = [x.score for x in (roic_s, roe_s) if x.score is not None]
    roc = statistics.fmean(parts) if parts else None
    items.append(Item(
        "return_on_capital", "High Return on Capital", WEIGHTS["return_on_capital"], roc,
        metric=f"ROIC {pct(dm.get('roic'))}, ROE {pct(dm.get('roe'))}",
        benchmark="country+industry+history",
        reason="Returns on invested capital and equity versus market, sector and the "
               "company's own history — high, sustained returns indicate quality.",
        positives=["Strong returns on invested capital"] if (roic_s.score or 0) >= 0.7 else [],
        negatives=["Returns on capital below benchmark"] if (roic_s.score or 1) < 0.4 else [],
    ))

    # 4. Conservative balance sheet — D/E + interest coverage (skipped for financials)
    de_s = sm("debt_to_equity")
    ic_s = sm("interest_coverage")
    bs_parts = [x.score for x in (de_s, ic_s) if x.score is not None]
    bs = statistics.fmean(bs_parts) if bs_parts else None
    items.append(Item(
        "balance_sheet", "Conservative Balance Sheet", WEIGHTS["balance_sheet"], bs,
        metric=(f"D/E {dm['debt_to_equity']:.2f}"
                if dm.get("debt_to_equity") is not None else "D/E —"),
        benchmark="country+industry (sector-adjusted)",
        reason="Leverage and interest coverage judged against sector-appropriate limits "
               "(bank/utility norms differ from industrials).",
        positives=["Low leverage / strong coverage"] if (bs or 0) >= 0.7 else [],
        negatives=["Elevated leverage relative to peers"] if (bs or 1) < 0.4 else [],
        available=bs is not None,
    ))

    # 5. Consistent earnings growth — revenue & EPS CAGR
    rg_s, eg_s = sm("revenue_cagr"), sm("eps_cagr")
    g_parts = [x.score for x in (rg_s, eg_s) if x.score is not None]
    growth = statistics.fmean(g_parts) if g_parts else None
    items.append(Item(
        "earnings_growth", "Consistent Earnings Growth", WEIGHTS["earnings_growth"], growth,
        metric=f"Rev CAGR {pct(dm.get('revenue_cagr'))}, EPS CAGR {pct(dm.get('eps_cagr'))}",
        benchmark="country+industry+history",
        reason="Multi-year revenue and EPS compound growth versus market and sector norms.",
        positives=["Compounding revenue and earnings"] if (growth or 0) >= 0.65 else [],
        negatives=["Weak or inconsistent growth"] if (growth or 1) < 0.4 else [],
        available=growth is not None,
    ))

    # 6. Strong free cash flow — FCF margin + cash conversion (CFO/NI)
    fcf_s = sm("fcf_margin")
    cfo = _f(getattr(cashflows[0], "operating_cash_flow", None)) if cashflows else None
    ni = _f(getattr(incomes[0], "net_income", None)) if incomes else None
    conv = (cfo / ni) if cfo is not None and ni not in (None, 0) and ni > 0 else None
    conv_score = min(1.0, conv / 1.2) if conv else None
    fcf_parts = [x for x in (fcf_s.score, conv_score) if x is not None]
    fcf = statistics.fmean(fcf_parts) if fcf_parts else None
    items.append(Item(
        "free_cash_flow", "Strong Free Cash Flow", WEIGHTS["free_cash_flow"], fcf,
        metric=f"FCF margin {pct(dm.get('fcf_margin'))}" + (f", CFO/NI {conv:.2f}" if conv else ""),
        benchmark="country+industry+history",
        reason="Free-cash-flow margin plus cash conversion (operating cash flow vs net "
               "income) — real cash generation, not just accounting profit.",
        positives=["Earnings backed by strong cash flow"] if (conv or 0) >= 1 else [],
        negatives=(["Cash conversion lags reported earnings"]
                   if conv is not None and conv < 0.8 else []),
        available=fcf is not None,
    ))

    # 7. Honest capital allocation — dilution + payout sanity + ROIC trend
    shares = _series(list(reversed(incomes)), "weighted_shares")
    dilution = (shares[-1] / shares[0] - 1) if len(shares) >= 2 and shares[0] else None
    roic_hist = _series(list(reversed(ratios)), "roic")
    roic_trend = (roic_hist[-1] - roic_hist[0]) if len(roic_hist) >= 2 else None
    ca_parts = []
    if dilution is not None:
        ca_parts.append(max(0.0, min(1.0, 0.7 - dilution * 5)))  # buybacks/no dilution good
    if roic_trend is not None:
        ca_parts.append(0.5 + max(-0.5, min(0.5, roic_trend * 5)))
    ca = statistics.fmean(ca_parts) if ca_parts else None
    items.append(Item(
        "capital_allocation", "Honest Capital Allocation", WEIGHTS["capital_allocation"], ca,
        metric=(f"Share change {pct(dilution)}" if dilution is not None else "—"),
        benchmark="dilution + ROIC trend",
        reason="Share-count trend (buybacks vs dilution) and the direction of returns on "
               "capital — disciplined allocators avoid empire-building and dilution.",
        positives=(["Shares flat/declining (shareholder-friendly)"]
                   if (dilution or 1) <= 0.005 else []),
        negatives=["Ongoing share dilution"] if (dilution or 0) > 0.03 else [],
        available=ca is not None,
    ))

    # 8. Stable margins — volatility of gross/op/net margin
    margin_stabs = [s for s in (
        _cv_stability(_series(ratios, "gross_margin")),
        _cv_stability(_series(ratios, "operating_margin")),
        _cv_stability(_series(ratios, "net_margin")),
    ) if s is not None]
    ms = statistics.fmean(margin_stabs) if margin_stabs else None
    items.append(Item(
        "stable_margins", "Stable Margins", WEIGHTS["stable_margins"], ms,
        metric=f"Net margin {pct(dm.get('net_margin'))}", benchmark="historical volatility",
        reason="Lower year-to-year variability in gross/operating/net margins scores higher "
               "— pricing power and cost control.",
        positives=["Consistent margins through the cycle"] if (ms or 0) >= 0.7 else [],
        negatives=["Volatile margins"] if (ms or 1) < 0.5 else [],
        available=ms is not None,
    ))

    # 9. High owner earnings — (NI + D&A - capex) margin ≈ FCF proxy
    da = _f(getattr(cashflows[0], "depreciation_amortization", None)) if cashflows else None
    capex = _f(getattr(cashflows[0], "capital_expenditure", None)) if cashflows else None
    rev = _f(getattr(incomes[0], "revenue", None)) if incomes else None
    owner = None
    owner_margin = None
    if ni is not None and rev not in (None, 0):
        oe = ni + (da or 0) + (capex or 0)  # capex stored negative
        owner_margin = oe / rev
        owner = max(0.0, min(1.0, owner_margin / 0.15))
    items.append(Item(
        "owner_earnings", "High Owner Earnings", WEIGHTS["owner_earnings"], owner,
        metric=(pct(owner_margin) if owner is not None else "—"),
        benchmark="owner-earnings margin",
        reason="Owner earnings ≈ net income + D&A − maintenance capex, as a share of "
               "revenue — the cash an owner could extract.",
        positives=["Healthy owner earnings"] if (owner or 0) >= 0.6 else [],
        negatives=["Capital-intensive; low owner earnings"] if (owner or 1) < 0.4 else [],
        available=owner is not None,
    ))

    # 10. Predictable business — revenue/EPS/CF stability
    pred_stabs = [s for s in (
        _cv_stability(_series(ratios, "revenue_cagr")),
        _cv_stability(_series(incomes, "revenue")),
        _cv_stability(_series(incomes, "net_income")),
    ) if s is not None]
    pred = statistics.fmean(pred_stabs) if pred_stabs else None
    items.append(Item(
        "predictable", "Predictable Business", WEIGHTS["predictable"], pred,
        metric="revenue/earnings stability", benchmark="historical volatility",
        reason="How steady revenue and earnings have been — predictable businesses are "
               "easier to value and less cyclical.",
        positives=["Steady, predictable results"] if (pred or 0) >= 0.7 else [],
        negatives=["Cyclical / hard to predict"] if (pred or 1) < 0.5 else [],
        available=pred is not None,
    ))

    # 11. Conservative accounting — CFO > NI, low accruals
    acc = None
    if cfo is not None and ni is not None and ni != 0:
        accrual = (ni - cfo) / abs(ni)
        acc = max(0.0, min(1.0, 0.7 - accrual))  # CFO >= NI → good
    items.append(Item(
        "conservative_accounting", "Conservative Accounting",
        WEIGHTS["conservative_accounting"], acc,
        metric=(f"CFO/NI {conv:.2f}" if conv else "—"), benchmark="accrual ratio",
        reason="Cash flow from operations relative to net income — earnings backed by cash "
               "(low accruals) indicate conservative accounting.",
        positives=["Cash-backed earnings"] if (conv or 0) >= 1 else [],
        negatives=["High accruals vs cash flow"] if acc is not None and acc < 0.5 else [],
        available=acc is not None,
    ))

    # 12. Attractive valuation — PE / EV-EBITDA / PB / earnings & FCF yield
    val_scores = [x.score for x in (sm("pe"), sm("ev_ebitda"), sm("pb"),
                                    sm("earnings_yield")) if x.score is not None]
    val = statistics.fmean(val_scores) if val_scores else None
    items.append(Item(
        "valuation", "Attractive Valuation", WEIGHTS["valuation"], val,
        metric=f"P/E {dm.get('pe'):.1f}" if dm.get("pe") else "P/E —",
        benchmark="country+industry+own history",
        reason="Valuation multiples and yields versus the market, the sector, and the "
               "company's own historical range — cheaper relative to quality scores higher.",
        positives=["Trades below typical valuation"] if (val or 0) >= 0.65 else [],
        negatives=["Valuation looks full/expensive"] if (val or 1) < 0.4 else [],
        available=val is not None,
    ))

    # 13. Management quality — insider signal + dilution + ROIC trend
    from app.models.corporate import InsiderSummary
    ins = db.get(InsiderSummary, security.id)
    ins_activity = str(ins.activity) if ins and ins.activity else ""
    mgmt_parts = []
    if ins is not None and ins.score is not None:
        mgmt_parts.append(_f(ins.score) / 100.0)
    if dilution is not None:
        mgmt_parts.append(max(0.0, min(1.0, 0.7 - dilution * 5)))
    if roic_trend is not None:
        mgmt_parts.append(0.5 + max(-0.5, min(0.5, roic_trend * 5)))
    mgmt = statistics.fmean(mgmt_parts) if mgmt_parts else None
    items.append(Item(
        "management", "Management Quality", WEIGHTS["management"], mgmt,
        metric=(ins_activity or "—"), benchmark="insider activity + dilution + ROIC trend",
        reason="Insider buying/selling, share dilution, and the trajectory of returns on "
               "capital as a read on management alignment and skill.",
        positives=["Insiders buying / aligned"] if ins_activity.endswith("buying") else [],
        negatives=["Insiders selling"] if ins_activity.endswith("selling") else [],
        available=mgmt is not None,
    ))

    # ── Coverage-weighted overall ────────────────────────────────────────────
    avail = [it for it in items if it.available and it.score is not None]
    if not avail:
        return None, {"items": [asdict(it) for it in items], "coverage": 0.0}
    total_w = sum(it.weight for it in avail)
    overall = sum(it.score * it.weight for it in avail) / total_w * 100.0
    coverage = total_w / sum(WEIGHTS.values())
    breakdown = {
        "overall": round(overall, 1),
        "category": category_for(overall),
        "coverage": round(coverage, 2),
        "items": [asdict(it) for it in items],
    }
    return round(overall, 1), breakdown


# ratios-row attribute names differing from metric keys (for history lookup)
_RATIO_ATTR = {
    "revenue_cagr": "revenue_cagr_3y", "eps_cagr": "eps_cagr_3y",
    "pe": "pe_ratio", "ev_ebitda": "ev_to_ebitda", "pb": "price_to_book", "peg": "peg_ratio",
}


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    ctx = build_context(db)
    q = select(Security).where(Security.is_active.is_(True))
    if limit is not None:
        q = q.limit(limit)
    securities = db.scalars(q).all()
    scored = 0
    for i, sec in enumerate(securities, 1):
        latest_score = db.scalar(
            select(Score).where(Score.security_id == sec.id).order_by(Score.as_of.desc()).limit(1)
        )
        if latest_score is None:
            continue
        overall, breakdown = compute_for_security(db, sec, ctx)
        latest_score.pabrai = overall
        latest_score.pabrai_breakdown = breakdown
        if overall is not None:
            scored += 1
        if i % 50 == 0:
            db.commit()
    db.commit()
    result = {"securities": len(securities), "scored": scored}
    log.info("compute_all pabrai: %s", result)
    return result
