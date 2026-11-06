"""A US portfolio holds American companies a fund could actually buy."""

from __future__ import annotations

import json
from pathlib import Path

from app.ingestion.rebalance_ledger import capped_picks
from app.ingestion.us_universe import Investable, load_domicile, qualified

Q = "2026-03-31"
DAY = "2026-05-29"


def page(tmp_path: Path, symbol: str, income: float = 100.0, shares: float = 1e8) -> None:
    doc = {"statements_ttm": {"income": [
        {"fiscal_date": "2026-03-28", "net_income": income, "weighted_shares": shares}]}}
    (tmp_path / f"{symbol}.json").write_text(json.dumps(doc), encoding="utf-8")


def check(tmp_path: Path, domicile: dict[str, str], price: float = 50.0) -> Investable:
    return Investable(tmp_path, {}, domicile, lambda s, d: (DAY, price))


def test_a_large_profitable_american_company_qualifies(tmp_path: Path) -> None:
    page(tmp_path, "AAPL", shares=1e9)

    assert check(tmp_path, {"AAPL": "United States"})("AAPL", Q, DAY)


def test_a_foreign_listing_does_not(tmp_path: Path) -> None:
    """HDB files in rupees and trades in dollars: it published a P/E of 0.48."""
    page(tmp_path, "HDB", shares=1e10)

    assert not check(tmp_path, {"HDB": "India"})("HDB", Q, DAY)


def test_a_name_the_listing_does_not_know_does_not(tmp_path: Path) -> None:
    page(tmp_path, "MYST", shares=1e10)

    assert not check(tmp_path, {"AAPL": "United States"})("MYST", Q, DAY)


def test_too_small_or_loss_making_does_not(tmp_path: Path) -> None:
    page(tmp_path, "TINY", shares=1e6)
    page(tmp_path, "LOSS", income=-5.0, shares=1e9)
    home = {"TINY": "United States", "LOSS": "United States"}

    assert not check(tmp_path, home)("TINY", Q, DAY)
    assert not check(tmp_path, home)("LOSS", Q, DAY)


def test_an_impossible_pe_does_not(tmp_path: Path) -> None:
    """Tencent Music: listed as American, accounts in yuan, a P/E of 1.45 on our figures."""
    page(tmp_path, "TME", income=4e9, shares=1.2e8)
    page(tmp_path, "FAIR", income=1e9, shares=1.2e8)
    home = {"TME": "United States", "FAIR": "United States"}

    assert not check(tmp_path, home)("TME", Q, DAY)
    assert check(tmp_path, home)("FAIR", Q, DAY)


def test_size_and_profit_are_judged_on_the_quarter_not_today(tmp_path: Path) -> None:
    page(tmp_path, "AAPL", shares=1e9)

    assert not check(tmp_path, {"AAPL": "United States"})("AAPL", "2023-03-31", "2023-05-31")


def test_a_price_far_from_the_trade_date_does_not_count(tmp_path: Path) -> None:
    page(tmp_path, "LATE", shares=1e9)
    late = Investable(tmp_path, {}, {"LATE": "United States"}, lambda s, d: ("2026-09-01", 50.0))

    assert not late("LATE", Q, DAY)


def test_the_ranking_keeps_its_order_with_the_rest_taken_out(tmp_path: Path) -> None:
    page(tmp_path, "A", shares=1e9)
    page(tmp_path, "B", shares=1e9)
    page(tmp_path, "C", shares=1e9)
    home = {"A": "United States", "B": "China", "C": "United States"}

    ranked = [("A", 90.0), ("B", 80.0), ("C", 70.0)]

    assert qualified(ranked, Q, DAY, check(tmp_path, home)) == [("A", 90.0), ("C", 70.0)]


def test_no_domicile_file_turns_the_filter_off_rather_than_emptying_the_book(tmp_path) -> None:
    assert load_domicile(tmp_path / "absent.csv") == {}
    page(tmp_path, "AAPL", shares=1e9)

    assert check(tmp_path, {})("AAPL", Q, DAY)


def test_a_held_name_stays_inside_the_buffer_and_goes_outside_it() -> None:
    ranked = [(f"N{i}", 100.0 - i) for i in range(40)]
    names = {s: {"sector": s} for s, _ in ranked}

    picks = capped_picks(ranked, names, 15, keep={"N20", "N35"}, buffer=30)

    assert "N20" in picks and "N35" not in picks and len(picks) == 15
    assert "N14" not in picks and "N13" in picks


def test_a_held_name_still_counts_to_the_sector_limit() -> None:
    ranked = [(f"B{i}", 100.0 - i) for i in range(6)] + [(f"X{i}", 50.0 - i) for i in range(12)]
    names = {s: {"sector": "Banks" if s[0] == "B" else s} for s, _ in ranked}

    picks = capped_picks(ranked, names, 12, keep={"B5"}, buffer=30)

    assert sum(s[0] == "B" for s in picks) == 3
    assert "B5" in picks
