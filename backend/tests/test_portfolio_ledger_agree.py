"""The portfolio and the quarterly history must describe ONE rule.

They did not. On 2026-08-06 all 35 holdings disagreed with the ledger on entry date, entry
price and return - not a rounding difference, a different answer on every row - for three
independent reasons:

  * the portfolio file was created on 2 August 2026 with no memory before it, so every holding
    claimed to have been bought on the then-current trade date. SAZEW read -12.89% against the
    +144% the rule had actually run; THCCL +23% against +768%;
  * the two used different month arithmetic - min(day, 28) against month-end - so one bought
    on 28 May and the other on 1 June, at different prices;
  * the portfolio held top-15 for the US while the ledger reconstructed top-20, so seven PSX
    and two US names existed on one page only.

The fix is structural rather than corrective: the ledger walks the rule and the portfolio IS
its open positions, so there is no second implementation left to drift.
"""

from __future__ import annotations

from datetime import date

from app.ingestion.model_portfolio import SIZE_BY_REGION, unadjusted_action


def _series(pairs: list[tuple[str, float]]) -> dict:
    """Bars in the shape load_bars returns - close is field 4."""
    return {day: [0, 0, 0, 0, close, 0] for day, close in pairs}


def test_a_tenfold_step_between_sessions_is_reported() -> None:
    """SRVI: 209 on 2026-06-01, 2,074 by August. A reverse split nobody applied, published
    as +897% until this caught it."""
    bars = _series([("2026-06-01", 209.13), ("2026-07-27", 207.0),
                    ("2026-07-28", 2078.0), ("2026-08-03", 2073.78)])
    found = unadjusted_action(bars, "2026-06-01", "2026-08-06")
    assert found is not None
    day, ratio = found
    assert day == "2026-07-28"
    assert ratio > 3


def test_a_forward_split_is_caught_in_the_other_direction() -> None:
    """A 5:1 that halves the series must trip the same wire as one that multiplies it."""
    bars = _series([("2025-01-02", 500.0), ("2025-01-03", 100.0), ("2025-02-01", 105.0)])
    assert unadjusted_action(bars, "2025-01-01", "2025-03-01") is not None


def test_an_ordinary_multibagger_is_left_alone() -> None:
    """THCCL ran 7.53 to 65.30 - eightfold, and real, because it happened gradually.

    The guard has to separate a rescaled series from a stock that simply went up a lot, or it
    suppresses exactly the results the page exists to show.
    """
    bars = _series([(f"2025-{m:02d}-01", 7.53 * (1.21 ** m)) for m in range(1, 13)])
    assert unadjusted_action(bars, "2025-01-01", "2025-12-31") is None


def test_the_window_is_respected() -> None:
    """A split BEFORE the holding was entered does not invalidate its return."""
    bars = _series([("2024-01-02", 500.0), ("2024-01-03", 100.0),
                    ("2025-06-01", 110.0), ("2025-09-01", 120.0)])
    assert unadjusted_action(bars, "2025-06-01", "2025-12-01") is None
    assert unadjusted_action(bars, "2024-01-01", "2025-12-01") is not None


def test_an_empty_or_flat_history_is_not_an_action() -> None:
    assert unadjusted_action({}, "2025-01-01", "2025-12-31") is None
    assert unadjusted_action(_series([("2025-01-02", 10.0)]), "2025-01-01", "2025-12-31") is None


def test_zero_and_negative_closes_do_not_divide() -> None:
    """A bad tick must not raise, and must not read as an infinite ratio."""
    bars = _series([("2025-01-02", 10.0), ("2025-01-03", 0.0), ("2025-01-06", 10.5)])
    assert unadjusted_action(bars, "2025-01-01", "2025-12-31") is None


def test_both_pages_size_each_market_the_same_way() -> None:
    """The ledger now reads SIZE_BY_REGION rather than a top_n of its own.

    This is the constant that stops the third divergence coming back: a reconstruction of a
    top-20 US history describes a rule the portfolio was not running.
    """
    from app.ingestion import rebalance_ledger

    assert rebalance_ledger.SIZE_BY_REGION is SIZE_BY_REGION
    assert SIZE_BY_REGION["psx"] == 20
    assert SIZE_BY_REGION["us"] == 15


def test_the_reconstruction_covers_only_complete_markets() -> None:
    """India at 58% and Australia at 67% scored would render a half-loaded universe as a
    record of the rule. They are excluded until their scrapes finish."""
    from app.cli import RECONSTRUCTED_REGIONS

    assert set(RECONSTRUCTED_REGIONS) == {"us", "psx"}


def test_a_quarter_end_plus_two_months_can_land_on_a_weekend() -> None:
    """The premise of restating traded_on: 12 of 39 rebalances did, and 2026-05-31 is Sunday.

    The target is only where the search starts - every published date is a session that filled.
    """
    assert date(2026, 5, 31).weekday() == 6
    assert date(2025, 11, 30).weekday() == 6
