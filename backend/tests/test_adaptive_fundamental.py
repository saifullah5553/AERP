"""The adaptive engine: pro-rata scoring, country adaptation, and the N/A path.

These test the three things that make this engine different from the one it replaced. Each
one exists because getting it wrong is invisible from the outside: a bank scored on inventory
looks like a bad bank, and a US company scored on Karachi thresholds looks expensive.
"""

from __future__ import annotations

from app.engines.fundamental.adaptive import BANK, GENERAL, classify_model, prorata
from app.engines.fundamental.adaptive_score import score_company


def _rows(n: int, **over):
    """n TTM periods of a plain, profitable manufacturer."""
    inc, bal, cf = [], [], []
    for i in range(n):
        g = (1.10 ** (-i))          # newest first, so older periods are smaller
        inc.append({
            "fiscal_date": f"20{26 - i // 4:02d}-12-31",
            "revenue": 1000.0 * g, "cost_of_revenue": 600.0 * g,
            "gross_profit": 400.0 * g, "operating_income": 200.0 * g,
            "income_before_tax": 180.0 * g, "income_tax_expense": 52.0 * g,
            "net_income": 128.0 * g, "interest_expense": 20.0 * g,
            "ebitda": 260.0 * g, "weighted_shares": 100.0,
            **over.get("income", {}),
        })
        bal.append({
            "fiscal_date": f"20{26 - i // 4:02d}-12-31",
            "total_assets": 2000.0 * g, "total_equity": 900.0 * g,
            "total_debt": 400.0 * g, "long_term_debt": 300.0 * g,
            "cash_and_equivalents": 150.0 * g, "current_assets": 800.0 * g,
            "current_liabilities": 500.0 * g, "inventory": 250.0 * g,
            "receivables": 200.0 * g, "accounts_payable": 180.0 * g,
            **over.get("balance", {}),
        })
        cf.append({
            "fiscal_date": f"20{26 - i // 4:02d}-12-31",
            "operating_cash_flow": 210.0 * g, "capital_expenditure": -60.0 * g,
            "free_cash_flow": 150.0 * g, "dividends_paid": -40.0 * g,
            "net_change_in_cash": 30.0 * g,
            **over.get("cashflow", {}),
        })
    return {"income": inc, "balance": bal, "cashflow": cf}


MARKET = {"price": 20.0, "market_cap": 2000.0}


def test_scoring_is_prorata_not_three_steps() -> None:
    """The whole point of pro-rata: values between anchors must differ.

    Under GOOD/AVERAGE/BAD banding every value from 5% to 15% collapsed to exactly 3, so a
    company at 14.9% and one at 5.1% were indistinguishable and the total jumped a full
    weighted point on a single basis point at the boundary.
    """
    low = prorata(0.051, 0.0, 0.05, 0.15)
    high = prorata(0.149, 0.0, 0.05, 0.15)
    assert 3.0 < low < 3.1, low
    assert 4.9 < high < 5.0, high
    assert high > low

    # Anchors still land exactly where the specification puts them.
    assert prorata(0.05, 0.0, 0.05, 0.15) == 3.0
    assert prorata(0.15, 0.0, 0.05, 0.15) == 5.0
    assert prorata(0.0, 0.0, 0.05, 0.15) == 1.0
    # And it saturates rather than running away above the top anchor.
    assert prorata(5.0, 0.0, 0.05, 0.15) == 5.0


def test_prorata_handles_lower_is_better() -> None:
    """P/E and friends run the other way; the same function must not invert them."""
    cheap = prorata(8.0, 24.0, 15.0, 10.0)
    dear = prorata(23.0, 24.0, 15.0, 10.0)
    assert cheap == 5.0
    assert dear < 2.0
    assert cheap > dear


def test_the_same_company_scores_differently_by_country() -> None:
    """A P/E of 20 is expensive in Karachi and unremarkable in New York.

    If this ever stops holding, the country table has been bypassed and every foreign company
    is being marked against Pakistani thresholds.
    """
    st = _rows(20)
    pk = score_company(st, "psx", sector="Industrials", market=MARKET)
    us = score_company(st, "us", sector="Industrials", market=MARKET)
    assert pk.percent is not None and us.percent is not None
    assert pk.country == "Pakistan" and us.country == "United States"
    assert pk.percent != us.percent


def test_a_bank_is_scored_on_the_financial_matrix_not_the_operating_one() -> None:
    """A bank gets its own nine metrics, not the operating fifteen with holes in them.

    Marking eleven of the fifteen N/A was the old answer and it left a bank assessed on
    whatever happened to survive - revenue growth, net profit growth, net margin and ROE.
    JPMorgan and UBL both scored exactly 100.0 on that remainder and outranked companies
    measured on all fifteen. Four metrics is not an assessment.
    """
    st = _rows(20)
    bank = score_company(st, "psx", sector="Commercial Banks", market=MARKET)
    plain = score_company(st, "psx", sector="Industrials", market=MARKET)

    assert bank.model == BANK
    assert plain.model == GENERAL

    keys = {m.key for m in bank.metrics}
    assert keys == {"sales_growth", "net_growth", "asset_growth", "book_value_growth",
                    "roe", "roa", "net_margin", "equity_to_assets", "earnings_stability"}
    # Nothing is N/A any more, because every one of the nine applies to a bank.
    assert not [m for m in bank.metrics if m.na_model]
    assert bank.applicable_count == 9

    # The operating-company metrics are simply absent, not scored badly.
    for gone in ("current_ratio", "quick_ratio", "interest_coverage", "gross_margin",
                 "free_cash_flow", "debt_to_equity", "roic"):
        assert gone not in keys

    # Both matrices are out of 100, so the two scores sit on the same scale.
    assert abs(bank.applicable_max - 100.0) < 1e-9
    assert abs(plain.applicable_max - 100.0) < 1e-9


def test_banks_and_insurers_are_measured_against_different_norms() -> None:
    """One set of thresholds would call every insurer over-capitalised and every bank thin.

    Measured across our own statements: median ROA is 1.0% for a bank and 2.7% for an insurer,
    equity to assets 10.7% against 27.5%, net margin 28.6% against 7.4% - because an insurer's
    revenue is premiums.
    """
    from app.engines.fundamental.financial import ANCHORS

    for metric in ("roa", "equity_to_assets", "net_margin"):
        assert ANCHORS["bank"][metric] != ANCHORS["insurer"][metric], metric
    # Every anchor triple must be ordered, or prorata reads the direction backwards.
    for model, table in ANCHORS.items():
        for metric, (bad, avg, good) in table.items():
            rising = good > bad
            assert (avg > bad and good > avg) if rising else (avg < bad and good < avg), \
                f"{model}.{metric} anchors are not monotonic"
    # Earnings stability is the one where LOWER is better, and it must be stated that way.
    assert ANCHORS["bank"]["earnings_stability"][2] < ANCHORS["bank"]["earnings_stability"][0]


def test_a_bank_is_not_penalised_for_being_a_bank() -> None:
    """Identical statements, one labelled a bank: the bank must not score materially worse.

    The redistribution is only correct if it actually neutralises the N/A metrics. If a bank
    came out far below an identical industrial, the weight was being dropped from the numerator
    without leaving the denominator.
    """
    st = _rows(20)
    bank = score_company(st, "psx", sector="Commercial Banks", market=MARKET)
    plain = score_company(st, "psx", sector="Industrials", market=MARKET)
    assert bank.percent is not None and plain.percent is not None
    assert abs(bank.percent - plain.percent) < 25.0, (bank.percent, plain.percent)


def test_an_exchange_is_not_classified_as_a_bank() -> None:
    """MCX is an exchange. The valuation engine already paid for this confusion once - it
    valued MCX at 398 against a price of 2,766 by anchoring a fee business on book value."""
    assert classify_model("Financial Services", "Financial Data & Stock Exchanges") == GENERAL
    assert classify_model("Financial Services", "Asset Management") == GENERAL


def test_a_generic_financial_label_is_resolved_from_the_balance_sheet() -> None:
    """1,465 rows carry the sector "Financial Services" and no industry. A deposit-funded bank
    is told apart from an operating company by leverage, absent inventory and interest share -
    not by the label, which cannot distinguish them."""
    bankish = {"total_assets": 20000.0, "total_equity": 1500.0, "inventory": None}
    income = {"interest_expense": 400.0, "revenue": 1200.0}
    assert classify_model("Financial Services", None, bankish, income) == BANK

    # An asset-light fee business with the same label is not a bank.
    light = {"total_assets": 1200.0, "total_equity": 800.0, "inventory": None}
    assert classify_model("Financial Services", None, light, income) == GENERAL


def test_missing_data_is_not_the_same_as_not_applicable() -> None:
    """Both leave a metric unscored, but only one may shrink the maximum for free.

    Treating them alike would reward a company for filing less: drop every absent metric from
    the denominator and a firm reporting almost nothing scores full marks on the little it does
    report.
    """
    # A REIT, not a bank: banks now have their own matrix with nothing marked N/A, so the
    # model-exclusion path has to be exercised on a model that still uses the operating one.
    st = _rows(20)
    reit = score_company(st, "psx", sector="REIT - Diversified", market=MARKET)
    by_model = [m for m in reit.metrics if m.na_model]
    assert by_model, "a REIT should have model-inapplicable metrics"
    assert all(m.score is None for m in by_model)
    # The two reasons are reported separately per category.
    liq = reit.categories["liquidity"]
    assert "na_model" in liq and "no_data" in liq


def test_a_company_reporting_almost_nothing_is_not_scored() -> None:
    """Coverage gate. An empty shell must come back Unrated, not flattered."""
    thin = {
        "income": [{"fiscal_date": "2026-03-31", "revenue": None, "net_income": -100.0}],
        "balance": [{"fiscal_date": "2026-03-31"}],
        "cashflow": [{"fiscal_date": "2026-03-31"}],
    }
    res = score_company(thin, "psx", sector="Industrials", market=MARKET)
    assert res.percent is None
    assert res.rating == "Unrated"


def test_growth_is_measured_even_on_short_history() -> None:
    """With only two years of filings the engine must still see growth.

    Insisting on a three-year window made growth silently ABSENT rather than visibly weak, and
    because the weight then left the total, a company growing 35% scored the same as one
    growing 2%.
    """
    fast = score_company(_rows(8), "psx", sector="Industrials", market=MARKET)
    sales = next(m for m in fast.metrics if m.key == "sales_growth")
    assert sales.value is not None
    assert sales.score is not None


def test_rating_bands_match_the_specification() -> None:
    from app.engines.fundamental.adaptive import rating_for

    assert rating_for(90.0) == "EXCEPTIONAL"
    assert rating_for(80.0) == "VERY STRONG"
    assert rating_for(70.0) == "STRONG"
    assert rating_for(60.0) == "AVERAGE / ACCEPTABLE"
    assert rating_for(50.0) == "WEAK"
    assert rating_for(20.0) == "POOR"


def test_category_weights_reproduce_the_stated_maxima() -> None:
    """Fifteen metrics, equal weight, totalling exactly 100.

    The specification lists the metrics and sets no weights, so they are equal - and that is a
    decision worth pinning. A later edit that quietly made one category heavier would change
    the meaning of every stored score without changing anything visible.
    """
    from app.engines.fundamental.adaptive import (
        CATEGORY_MAX,
        CATEGORY_METRICS,
        CATEGORY_WEIGHT,
        FIN_CATEGORY_METRICS,
        FIN_METRIC_COUNT,
        FIN_PER_METRIC,
        GOOD,
        METRIC_WEIGHT_COUNT,
        PER_METRIC,
        TOTAL_MAX,
    )

    assert sum(CATEGORY_METRICS.values()) == METRIC_WEIGHT_COUNT == 15
    assert sum(FIN_CATEGORY_METRICS.values()) == FIN_METRIC_COUNT == 9

    # Each matrix totals 100 on its own, so a bank's score and a manufacturer's sit on the
    # same scale even though they were reached by counting different things.
    for metrics, per in ((CATEGORY_METRICS, PER_METRIC),
                         (FIN_CATEGORY_METRICS, FIN_PER_METRIC)):
        for cat, n in metrics.items():
            assert abs(GOOD * CATEGORY_WEIGHT[cat] / 100 * n - CATEGORY_MAX[cat]) < 1e-9, cat
        assert abs(sum(CATEGORY_MAX[c] for c in metrics) - TOTAL_MAX) < 1e-9
        assert abs(per * sum(metrics.values()) - TOTAL_MAX) < 1e-9
        # Equal per metric WITHIN a matrix. Grouping is presentation, not weight.
        assert len({CATEGORY_WEIGHT[c] for c in metrics}) == 1


def test_every_metric_of_the_matrix_is_present_and_nothing_else() -> None:
    """The fifteen, by name. A metric added or dropped without the specification changing
    would move every score, and this is the only place that would notice."""
    res = score_company(_rows(20), "psx", sector="Industrials", market=MARKET)
    assert {m.key for m in res.metrics} == {
        "sales_growth", "op_growth", "net_growth",
        "gross_margin", "operating_margin", "net_margin",
        "debt_to_equity", "interest_coverage",
        "roe", "roic",
        "current_ratio", "quick_ratio",
        "cfo_vs_net_income", "operating_cash_flow", "free_cash_flow",
    }


def test_interest_coverage_uses_the_magnitude_of_a_negative_expense() -> None:
    """The store signs interest expense NEGATIVE for 8,364 companies against 150 positive.

    Reading it as a signed number meant the ``interest > 0`` test almost never fired, every
    company fell through to the "nothing to cover" default, and 98.3% of the universe scored a
    perfect 5. A metric that returns the same answer for everyone is broken, not lenient.
    """
    # Negative, as the store actually writes it.
    thin = _rows(20, income={"operating_income": 1000.0,
                             "interest_expense": -500.0})   # 2x cover: weak
    thick = _rows(20, income={"operating_income": 1000.0,
                              "interest_expense": -20.0})   # 50x cover: strong
    weak = next(m for m in score_company(thin, "psx", sector="Industrials",
                                         market=MARKET).metrics
                if m.key == "interest_coverage")
    strong = next(m for m in score_company(thick, "psx", sector="Industrials",
                                           market=MARKET).metrics
                  if m.key == "interest_coverage")
    assert weak.value is not None and weak.value == 2.0
    assert strong.value == 50.0
    assert weak.score is not None and strong.score is not None
    assert weak.score < strong.score


def test_a_metric_is_read_at_the_latest_period_that_reports_it() -> None:
    """The newest TTM column is null for 19% of inventory and 10% of current assets, and no
    company has a field null in EVERY column. Reading index 0 alone treated those reporting
    lags as absent and dropped roughly a third of Indian companies out of liquidity."""
    st = _rows(20)
    # Blank the newest two periods of the current-ratio inputs only.
    for row in st["balance"][:2]:
        row["current_assets"] = None
        row["current_liabilities"] = None
    res = score_company(st, "psx", sector="Industrials", market=MARKET)
    cr = next(m for m in res.metrics if m.key == "current_ratio")
    assert cr.value is not None, "should fall back to the newest period that reports it"
    assert cr.score is not None
    assert "back" in cr.note or "old" in cr.note, "and must say the figure is not current"


def test_the_grade_always_matches_its_own_score() -> None:
    """The label and the number must never disagree.

    They did: a rescore moved the score and left the label from the previous run, so 3,143 of
    9,602 rows carried a grade from a band their own score no longer sat in - JPMorgan read
    61.6 labelled VERY STRONG. A trader reading the label got a different answer from one
    reading the number, on the same row.
    """
    import json
    import tempfile
    from pathlib import Path

    from app.ingestion.score_unify import unify

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "company").mkdir()
        rows = [
            # A stale label from a previous run, one band too high.
            {"provider_symbol": "AAA", "quality_score": 61.6, "quality_grade": "VERY STRONG"},
            {"provider_symbol": "BBB", "quality_score": 86.5, "quality_grade": "VERY STRONG"},
            # No score: the label must go too, not linger.
            {"provider_symbol": "CCC", "quality_score": None, "quality_grade": "STRONG"},
        ]
        (d / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
        unify(d)
        out = {r["provider_symbol"]: r
               for r in json.loads((d / "screener.json").read_text(encoding="utf-8"))}
        assert out["AAA"]["quality_grade"] == "AVERAGE / ACCEPTABLE"
        assert out["BBB"]["quality_grade"] == "EXCEPTIONAL"
        assert out["CCC"]["quality_grade"] is None
