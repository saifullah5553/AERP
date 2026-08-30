"""Assemble the adaptive fundamental score: normalise, rate, classify.

The arithmetic that matters is in `_normalise`. Weighted points earned are divided by the
maximum the APPLICABLE metrics could have earned, not by the framework total, so a bank with
thirteen N/A metrics is measured against the metrics it can actually have. Dividing by the
full 145.5 instead would guarantee every bank scored badly and would look, from the outside,
exactly like banks being bad businesses.
"""

from __future__ import annotations

from app.engines.fundamental.adaptive import (
    BANK,
    CATEGORY_LABEL,
    CATEGORY_MAX,
    COUNTRIES,
    DEFAULT_COUNTRY,
    INSURER,
    MODEL_NOTE,
    TOTAL_MAX,
    AdaptiveResult,
    Metric,
    _tier,
    classify_model,
    rating_for,
)
from app.engines.fundamental.adaptive_metrics import (
    accounting_flags,
    build_metrics,
    piotroski_score,
    risk_from_flags,
)
from app.engines.fundamental.financial import classify_financial

# Four of the fifteen. The matrix is a quarter the size of the framework it replaces, so the
# old count of eight would now refuse whole business models rather than thin data: with its
# cash-flow metrics marked N/A a bank has exactly four that can apply - revenue growth, net
# profit growth, net margin and return on equity - and refusing every bank would have looked
# from the outside exactly like banks being bad businesses.
#
# Four metrics IS thin, and the answer to that is to say so rather than to hide it: the
# result carries `scored_count` and `applicable_count` so a page can print "scored on 4 of
# 15" beside the number instead of letting it pass for a full assessment.
MIN_SCORED_METRICS = 4
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


# Growth is the only leg of this matrix that carries a DIRECTION; the other twelve metrics are
# levels measured at a point in time. The framework this replaced compared three-year against
# five-year averages for ten of its metrics, and those comparisons are gone with the metrics.
# Reading a trend off the levels instead would just be the score again under another name.
_TREND_KEYS = {"sales_growth", "op_growth", "net_growth"}


def _trend(metrics: list[Metric]) -> str:
    """Improving / Stable / Deteriorating, from the growth metrics alone."""
    scored = [m.score for m in metrics if m.key in _TREND_KEYS and m.score is not None]
    if len(scored) < 2:
        return "Unknown"
    avg = sum(scored) / len(scored)
    if avg >= 3.6:
        return "Improving"
    if avg <= 2.4:
        return "Deteriorating"
    return "Stable"


def _classify(growth: str, quality: str, strength: str, cash: str, trend: str) -> str:
    """What KIND of business this is, from the four things the matrix measures.

    Every valuation-dependent label the previous framework produced - Value Trap, Deep Value,
    Growth at a Reasonable Price, High-Quality Expensive - has been removed rather than
    guessed at. This matrix does not score valuation, so it cannot know whether a company is
    cheap, and a classification that implied it did would be the single most misleading thing
    on the page. Whether the price is right is the valuation engine's answer.
    """
    strong = {"Exceptional", "Strong"}
    weak = {"Weak"}

    if strength in weak and cash in weak:
        return "Financially Stressed"
    # The POSITIVE patterns are tested before Turnaround, because Turnaround only means
    # anything about a company that is currently struggling. Testing it first labelled Apple -
    # 87%, every growth and margin metric at full marks - a turnaround, on the strength of a
    # current ratio near 1.0 and rising profits.
    if growth in strong and quality in strong and cash in strong and strength in strong:
        return "Quality Compounder"
    if quality in strong and cash in strong and growth in strong:
        return "Profitable & Growing"
    if growth == "Exceptional":
        return "High-Growth Company"
    if quality in strong and cash in strong:
        return "Profitable & Cash-Generative"
    if strength in strong and cash in strong and growth in weak:
        return "Mature Stable Business"
    if trend == "Improving" and (growth in weak or strength in weak):
        return "Turnaround"
    if growth in weak and quality in weak:
        return "Cyclical or Marginal"
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

    # Piotroski is REPORTED but no longer SCORED. It is not one of the fifteen, and it is not
    # an independent sixteenth either: seven of its nine tests are the same profitability,
    # leverage, liquidity and cash-conversion facts the matrix already scores, so including it
    # would count them twice. It stays on the record because a single 0-9 summary is useful to
    # read next to the score.
    # Not for financials: the F-Score's nine tests assume gross margin, asset turnover,
    # current ratio and leverage read the way they do for an operating company. Running it on
    # a bank produces a number with no meaning rather than a missing one.
    res.piotroski = None if model in (BANK, INSURER) else piotroski_score(inc, bal, cf)

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
    # A company with one reported period cannot have a growth rate, and counting the three
    # growth metrics as gaps would put every new listing below the gate for a reason that has
    # nothing to do with how well it reports.
    history_short = len(inc) < 8
    denom = [m for m in metrics
             if not m.na_model
             and not (history_short and m.key in _TREND_KEYS)]
    applicable_metrics = len(denom)
    scored_in_denom = sum(1 for m in denom if m.score is not None)
    coverage = (scored_in_denom / applicable_metrics) if applicable_metrics else 0.0
    res.coverage = round(coverage, 3)
    res.scored_count = scored
    res.applicable_count = sum(1 for m in metrics if not m.na_model)
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

    def pct(*keys: str) -> float | None:
        """Combined percentage across categories, weighted by what each could have earned -
        so a category whose metrics were all N/A contributes nothing instead of dragging the
        pair toward zero."""
        earned = sum(cats.get(k, {}).get("earned") or 0.0 for k in keys)
        cap = sum(cats.get(k, {}).get("applicable_max") or 0.0 for k in keys)
        return round(earned / cap * 100, 1) if cap else None

    if model in (BANK, INSURER):
        # The financial matrix has no cash-flow leg - a bank's operating cash flow tracks
        # deposit and loan flows, not performance - so it is classified on its own three axes
        # rather than being fed a fourth that would always read "Unknown".
        res.matrix = {
            "growth": _tier(pct("fin_growth")),
            "profitability": _tier(pct("fin_profitability")),
            "capital": _tier(pct("fin_capital")),
        }
        res.classification = classify_financial(
            res.matrix["growth"], res.matrix["profitability"], res.matrix["capital"],
            res.trend)
    else:
        res.matrix = {
            "growth": _tier(pct("growth")),
            "quality": _tier(pct("margins", "returns")),
            "strength": _tier(pct("leverage", "liquidity")),
            "cash_flow": _tier(pct("cash_flow")),
        }
        res.classification = _classify(res.matrix["growth"], res.matrix["quality"],
                                       res.matrix["strength"], res.matrix["cash_flow"],
                                       res.trend)
    return res


__all__ = ["score_company", "AdaptiveResult"]
