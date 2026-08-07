"""The re-specified engine: six categories, liquidity on its own, ROIC scored once.

The weights changed for a reason that shows up in what they now measure:

    C  Cash flow & earnings quality   20 -> 25   the heaviest category
    E  Liquidity & cash reserves       0 -> 10   previously two ratios buried in D
    F  Working capital & efficiency    5 -> 10   now holds ROIC and asset turnover
       Capital efficiency             20 -> 0    dissolved into B and F

Cash flow carries the most weight deliberately: reported profit is an opinion until it turns
up as cash, so the category that checks whether it did should outweigh the one that reports it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.engines.strategy.fundamental_quality import (  # noqa: E402
    CATEGORY_POINTS,
    score_fundamentals,
)
from app.ingestion.quality_history import _history_stats, _trend  # noqa: E402

from test_fundamental_quality import _company  # noqa: E402


# ── the specified shape ─────────────────────────────────────────────────────────────────
def test_the_six_categories_and_their_budgets() -> None:
    assert CATEGORY_POINTS == {
        "growth": 20.0, "profitability": 20.0, "cash_flow": 25.0,
        "balance_sheet": 15.0, "liquidity": 10.0, "working_capital": 10.0,
    }
    assert sum(CATEGORY_POINTS.values()) == 100.0


def test_cash_flow_is_the_heaviest_category() -> None:
    """Not decoration - it is the design. Earnings quality outranks earnings."""
    assert CATEGORY_POINTS["cash_flow"] > max(
        v for k, v in CATEGORY_POINTS.items() if k != "cash_flow")


def test_every_category_is_reported_for_a_normal_company() -> None:
    res = score_fundamentals(_company())
    assert set(res.categories) == set(CATEGORY_POINTS)


# ── ROIC is scored exactly once ─────────────────────────────────────────────────────────
def test_roic_is_scored_once_and_as_a_return_measure() -> None:
    """The spec lists ROIC under both B and F. Scoring it twice would let one characteristic
    carry a fifth of the total through the back door - the double-counting section 27 warns
    against.

    It belongs in PROFITABILITY. ROIC is the return earned on the capital actually put into the
    business, the figure compared against the cost of that capital to judge whether value is
    created at all. That is a profitability question. Asset turnover and the cash cycle are the
    operational drivers behind it, and they stay in F.
    """
    res = score_fundamentals(_company())
    homes = [name for name, cat in res.categories.items()
             if "roic" in (cat.get("parts") or {})]
    assert homes == ["profitability"], f"roic scored in {homes}"


def test_returns_move_profitability_not_only_margins() -> None:
    """Margins say what the business keeps per sale; ROIC says whether the sale was worth
    financing. A company can hold a fat margin on capital it never earns back, and a
    margin-only category cannot tell the two apart.

    Behavioural rather than a weight assertion: the same margins with a rising return must
    score higher, which is the property that matters and survives a reweighting.
    """
    flat = score_fundamentals(_company(roic_drift=0.0))
    rising = score_fundamentals(_company(roic_drift=0.6))
    assert (rising.categories["profitability"]["earned"]
            > flat.categories["profitability"]["earned"])


def test_repayment_capacity_is_scored_not_the_raw_debt_total() -> None:
    """The CFA answer to "profit up, cash flow up, debt down": FCF against total debt - the
    share of borrowings a year of free cash could retire. It rises when cash generation
    outpaces borrowing and falls when it does not, without punishing a company for funding a
    larger business with a larger balance sheet."""
    res = score_fundamentals(_company())
    parts = res.categories["balance_sheet"]["parts"]
    assert "fcf_to_debt" in parts and parts["fcf_to_debt"] is not None
    assert "debt_trend" not in parts, "the raw debt total is being trended again"

    # More cash against the same debt must read as stronger.
    weak = score_fundamentals(_company(cfo_ratio=0.4))
    strong = score_fundamentals(_company(cfo_ratio=1.4))
    assert (strong.categories["balance_sheet"]["parts"]["fcf_to_debt"]
            > weak.categories["balance_sheet"]["parts"]["fcf_to_debt"])


# ── E. liquidity, which did not exist before ────────────────────────────────────────────
def test_liquidity_rewards_cash_against_obligations_not_the_size_of_the_pile() -> None:
    """"Do not simply reward the largest absolute cash balance." Two companies with identical
    cash and different debts must not score the same."""
    light = score_fundamentals(_company(leverage=0.2)).categories["liquidity"]["earned"]
    heavy = score_fundamentals(_company(leverage=2.0)).categories["liquidity"]["earned"]
    assert light > heavy


def test_net_cash_is_recognised() -> None:
    """Holding more cash than debt is a step change in resilience, not a point on a line."""
    res = score_fundamentals(_company(leverage=0.05))
    assert res.categories["liquidity"]["parts"]["net_cash_position"] == 1.0


# ── D. leverage direction is relative, never absolute ───────────────────────────────────
def test_growing_the_business_is_not_scored_as_taking_on_debt() -> None:
    """A company funding a bigger business with a proportionally bigger balance sheet has not
    weakened. Trending the raw debt total docked 0.7 balance-sheet points from a company purely
    for compounding at 25% instead of 10%."""
    slow = score_fundamentals(_company(growth=0.10)).categories["balance_sheet"]["earned"]
    fast = score_fundamentals(_company(growth=0.25)).categories["balance_sheet"]["earned"]
    assert abs(fast - slow) < 0.05, "growth is moving the leverage score"


def test_magnitude_survives_the_reweighting() -> None:
    """The whole range must stay monotonic, not just the two ends."""
    scores = [score_fundamentals(_company(growth=g)).score
              for g in (0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)]
    assert scores == sorted(scores), scores
    assert scores[-1] - scores[0] > 4


# ── F. working capital discipline ───────────────────────────────────────────────────────
def test_receivables_outrunning_revenue_is_penalised() -> None:
    """Revenue +10% on receivables +30% is the classic tell that sales are not becoming cash."""
    healthy = _company(growth=0.10)
    strained = _company(growth=0.10)
    # inflate the newest receivables only - i=0 is the newest row
    strained["balance"][0]["receivables"] *= 1.6
    a = score_fundamentals(healthy).categories["working_capital"]["parts"]
    b = score_fundamentals(strained).categories["working_capital"]["parts"]
    assert b["receivables_vs_revenue"] < a["receivables_vs_revenue"]


# ── the six-level trend, fitted over the whole history ──────────────────────────────────
def _series(scores: list[float]) -> list[dict]:
    return [{"score": s, "period": "ttm", "date": f"20{20 + i // 4}-01-01"}
            for i, s in enumerate(scores)]


def test_a_round_trip_is_mixed_not_stable() -> None:
    """50 -> 80 -> 50. First-versus-last called this unchanged; it was not a stable five
    years, and that answer was being published."""
    label, _ = _trend(_series([50, 60, 70, 80, 75, 65, 55, 50]))
    assert label == "mixed"


def test_a_steady_climb_is_strongly_improving() -> None:
    label, step = _trend(_series([50, 54, 58, 62, 66, 70, 74, 78]))
    assert label == "strongly_improving"
    assert step == 4.0        # the LATEST step, not the whole span


def test_a_steady_slide_is_strongly_deteriorating() -> None:
    label, _ = _trend(_series([78, 74, 70, 66, 61, 57, 53, 49]))
    assert label == "strongly_deteriorating"


def test_a_flat_line_is_stable() -> None:
    label, _ = _trend(_series([61, 62, 61, 60, 61, 62, 61, 61]))
    assert label == "stable"


def test_a_gentle_drift_is_improving_not_strongly() -> None:
    label, _ = _trend(_series([60, 61, 62, 63, 64, 65, 66, 68]))
    assert label == "improving"


def test_the_change_is_the_latest_step() -> None:
    """The most recent fundamental signal is this TTM against the last one - not the
    five-year span, which is what the label already carries."""
    _, step = _trend(_series([50, 55, 60, 62, 61, 68]))
    assert step == 7.0


def test_too_short_to_fit_falls_back_rather_than_inventing_a_trend() -> None:
    assert _trend(_series([60, 70]))[0] == "improving"
    assert _trend([])[0] == "unknown"


# ── latest against the company's own record ─────────────────────────────────────────────
def test_percentile_places_the_latest_score_in_its_own_history() -> None:
    """62 means one thing for a company that has never been above 60 and another for one that
    spent four years in the eighties."""
    stats = _history_stats(_series([40, 45, 50, 55, 60, 62]))
    assert stats["score_high"] == 62 and stats["score_low"] == 40
    assert stats["score_percentile"] == 100.0
    stats = _history_stats(_series([88, 85, 80, 75, 70, 62]))
    assert stats["score_percentile"] < 20


def test_stats_on_an_empty_history_are_empty_not_zero() -> None:
    assert _history_stats([]) == {}
