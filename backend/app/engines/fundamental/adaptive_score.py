"""Assemble the adaptive fundamental score: normalise, rate, classify.

The arithmetic that matters is in `_normalise`. Weighted points earned are divided by the
maximum the APPLICABLE metrics could have earned, not by the framework total, so a bank with
thirteen N/A metrics is measured against the metrics it can actually have. Dividing by the
full 145.5 instead would guarantee every bank scored badly and would look, from the outside,
exactly like banks being bad businesses.
"""

from __future__ import annotations

from app.engines.fundamental.adaptive import (
    CATEGORY_LABEL,
    CATEGORY_MAX,
    COUNTRIES,
    DEFAULT_COUNTRY,
    MODEL_NOTE,
    TOTAL_MAX,
    AdaptiveResult,
    Metric,
    _tier,
    _valuation_tier,
    classify_model,
    rating_for,
)
from app.engines.fundamental.adaptive_metrics import (
    accounting_flags,
    build_metrics,
    piotroski_score,
    prorata,
    risk_from_flags,
)

MIN_SCORED_METRICS = 8
# Over half the computable metrics must actually compute. 0.60 was the first value tried and
# it refused a company with 7 of 12 - thin, but a real business with real statements, and the
# established contract here is that such a company is thinly rated rather than unrated.
MIN_COVERAGE = 0.55


def _normalise(metrics: list[Metric]) -> tuple[float, float, dict[str, dict]]:
    """(earned, applicable_max, per-category detail)."""
    earned = applicable = 0.0
    cats: dict[str, dict] = {}
    for m in metrics:
        cat = cats.setdefault(m.category, {
            "label": CATEGORY_LABEL[m.category],
            "earned": 0.0, "applicable_max": 0.0,
            "original_max": CATEGORY_MAX[m.category],
            "scored": 0, "na_model": 0, "no_data": 0,
        })
        if m.score is None:
            cat["na_model" if m.na_model else "no_data"] += 1
            continue
        cat["earned"] += m.weighted or 0.0
        cat["applicable_max"] += m.max_weighted
        cat["scored"] += 1
        earned += m.weighted or 0.0
        applicable += m.max_weighted
    for cat in cats.values():
        cat["earned"] = round(cat["earned"], 2)
        cat["applicable_max"] = round(cat["applicable_max"], 2)
        cat["percent"] = (round(cat["earned"] / cat["applicable_max"] * 100, 1)
                          if cat["applicable_max"] else None)
    return earned, applicable, cats


_TREND_KEYS = {"eps_trend", "total_debt", "cfo_trend", "fixed_asset_turnover",
               "inventory_turnover", "dso", "dio", "dpo", "ccc", "fcf_per_share",
               "sales_cagr", "op_cagr", "net_cagr", "piotroski"}


def _trend(metrics: list[Metric]) -> str:
    """Improving / Stable / Deteriorating, from the 3Y-vs-5Y comparisons alone.

    Only those metrics carry a direction; scoring the level again here would double-count the
    same fundamentals the categories already measured.
    """
    keys = {"eps_trend", "total_debt", "cfo_trend", "fixed_asset_turnover",
            "inventory_turnover", "dso", "dio", "dpo", "ccc", "fcf_per_share"}
    scored = [m.score for m in metrics if m.key in keys and m.score is not None]
    if len(scored) < 2:
        return "Unknown"
    avg = sum(scored) / len(scored)
    if avg >= 3.6:
        return "Improving"
    if avg <= 2.4:
        return "Deteriorating"
    return "Stable"


def _classify(growth: str, stability: str, cash: str, value: str, trend: str) -> str:
    """Section 18 - do not confuse cheap with good."""
    strong = {"Exceptional", "Strong"}
    weak = {"Weak"}
    cheap = value in {"Very Attractive", "Attractive"}
    dear = value in {"Expensive", "Very Expensive"}

    if growth in weak and stability in weak:
        return "Financially Stressed" if cash in weak else "Value Trap" if cheap else "Cyclical"
    if cheap and (stability in weak or trend == "Deteriorating"):
        return "Value Trap"
    if trend == "Improving" and (growth in weak or stability in weak):
        return "Turnaround"
    if growth in strong and stability in strong and cash in strong:
        return "Quality Compounder" if not dear else "High-Quality Expensive"
    if growth == "Exceptional":
        return "High-Growth Company" if dear else "Growth at Reasonable Price"
    if cheap and stability in strong and cash in strong:
        return "Deep Value"
    if stability in strong and cash in strong:
        return "Mature Income Company"
    # No pattern matched. "Cyclical" was the old fallback and it was a claim we had not earned -
    # it labelled a perfectly ordinary bank scoring 70% as a cyclical business.
    return "Unclassified"


def score_company(statements: dict[str, list[dict]], region: str,
                  sector: str | None = None, industry: str | None = None,
                  market: dict | None = None,
                  peers: dict | None = None) -> AdaptiveResult:
    inc = statements.get("income") or []
    bal = statements.get("balance") or []
    cf = statements.get("cashflow") or statements.get("cash_flow") or []

    country = COUNTRIES.get(region, DEFAULT_COUNTRY)
    # The newest statements go to the classifier, because a generic "Financial Services" label
    # can only be resolved by looking at the balance sheet.
    model = classify_model(sector, industry,
                           balance=bal[0] if bal else None,
                           income=inc[0] if inc else None)
    res = AdaptiveResult(country=country.name, country_why=country.why, model=model,
                         model_note=MODEL_NOTE.get(model, ""))

    if not inc:
        return res

    metrics = build_metrics(inc, bal, cf, region, model, market, peers)

    pio = piotroski_score(inc, bal, cf)
    res.piotroski = pio
    # Piotroski sits in the cash-flow category as the fifth metric, mapped onto the same 1..5
    # scale: 0 of 9 anchors 1, 9 of 9 anchors 5, everything between is pro-rata.
    metrics.append(Metric(
        "piotroski", "cash_flow", "Piotroski F-Score",
        value=None if pio is None else float(pio),
        score=None if pio is None else prorata(float(pio), 0.0, 4.5, 9.0),
        benchmark="7-9 good / 4-6 average",
    ))

    res.metrics = metrics
    earned, applicable, cats = _normalise(metrics)
    res.raw_earned = earned
    res.applicable_max = applicable
    res.categories = cats

    scored = sum(1 for m in metrics if m.score is not None)
    # Coverage measures SPARSENESS, so its denominator must exclude metrics whose absence is
    # structural rather than sparse. A company with one reported period cannot have a
    # three-year-versus-five-year comparison, and counting those ten as gaps would put every
    # new listing below the gate for a reason that has nothing to do with data quality.
    history_short = len(inc) < 8
    # Same reasoning for valuation: with no quote, all eight valuation metrics are absent
    # because we could not price the company, not because it reports poorly. The engine this
    # replaces made the same allowance deliberately - a company we cannot price must not be
    # scored as though it were expensive.
    unpriced = not (market or {}).get("price") and not (market or {}).get("market_cap")
    denom = [m for m in metrics
             if not m.na_model
             and not (history_short and m.key in _TREND_KEYS)
             and not (unpriced and m.category == "valuation")]
    applicable_metrics = len(denom)
    scored_in_denom = sum(1 for m in denom if m.score is not None)
    coverage = (scored_in_denom / applicable_metrics) if applicable_metrics else 0.0
    res.coverage = round(coverage, 3)
    # Two gates, because they catch different things. The count stops a company with three
    # measurable metrics from being ranked beside one with thirty. The RATIO stops a company
    # from being flattered by absence: renormalising over whatever happens to be present would
    # let a firm that reports almost nothing score 100% on the little it does report.
    if scored < MIN_SCORED_METRICS or coverage < MIN_COVERAGE or applicable <= 0:
        # Too little to judge. Deliberately no score rather than a low one: an absent
        # measurement and a bad measurement must not look the same on the screener.
        res.rating = "Unrated"
        return res

    res.percent = round(earned / applicable * 100.0, 1)
    res.score = round(res.percent / 100.0 * TOTAL_MAX, 2)
    res.rating = rating_for(res.percent)

    flags = accounting_flags(inc, bal, cf)
    res.accounting_flags = flags
    res.accounting_risk = risk_from_flags(flags)
    res.trend = _trend(metrics)

    g = cats.get("growth", {}).get("percent")
    s = cats.get("stability", {}).get("percent")
    cflow = cats.get("cash_flow", {}).get("percent")
    v = cats.get("valuation", {}).get("percent")
    res.matrix = {
        "growth": _tier(g),
        "stability": _tier(s),
        "cash_flow": _tier(cflow),
        "valuation": _valuation_tier(v),
    }
    res.classification = _classify(res.matrix["growth"], res.matrix["stability"],
                                   res.matrix["cash_flow"], res.matrix["valuation"],
                                   res.trend)
    return res


__all__ = ["score_company", "AdaptiveResult"]
