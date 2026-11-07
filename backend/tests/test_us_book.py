"""From 6 Nov 2026 the US book is a dated record, not a reconstruction."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.ingestion import rebalance_ledger, us_book
from app.ingestion.rebalance_ledger import build_region
from app.ingestion.us_book import add_rebalance, load_book, qualifies, read_screen, select

HOME = {"AAA": "United States"}


def row(symbol: str, score: float = 80.0, sector: str = "Tech", market: str = "NYSE") -> dict:
    return {"region": "us", "symbol": symbol, "quality_score": score, "sector": sector,
            "technical_as_of": "2026-11-06",
            "market_code": market}


def screen(f0: float = 20.0, f1: float = 20.0, f2: float = 20.0, n: float = 5.0) -> dict:
    return {"AAA": {"f0": f0, "f1": f1, "f2": f2, "analysts": n}}


def test_a_name_passing_everything_qualifies() -> None:
    assert qualifies(row("AAA"), screen(), HOME)


@pytest.mark.parametrize("estimate", [screen(f0=14.9), screen(f1=14.9), screen(f2=14.9),
                                      screen(n=2)])
def test_each_growth_rate_and_the_analyst_count_must_pass(estimate) -> None:
    assert not qualifies(row("AAA"), estimate, HOME)


def test_exactly_fifteen_percent_passes() -> None:
    assert qualifies(row("AAA"), screen(15.0, 15.0, 15.0), HOME)


def test_our_score_and_the_exchange_count() -> None:
    assert not qualifies(row("AAA", score=69.9), screen(), HOME)
    assert not qualifies(row("AAA", market="OTC"), screen(), HOME)
    assert qualifies(row("AAA", market="NASDAQ"), screen(), HOME)
    assert not qualifies({**row("AAA"), "region": "india"}, screen(), HOME)


def test_size_is_not_a_condition() -> None:
    assert qualifies({**row("AAA"), "market_cap": 1e8}, screen(), HOME)


def test_a_foreign_listing_qualifies_once_its_score_is_on_its_own_basis() -> None:
    assert qualifies(row("AAA"), screen(), {"AAA": "China"}, basis={"AAA"})


def test_a_foreign_listing_waits_while_its_score_cannot_be_trusted() -> None:
    assert not qualifies(row("AAA"), screen(), {"AAA": "China"})


def test_a_name_not_on_the_screen_does_not_qualify() -> None:
    assert not qualifies(row("BBB"), screen(), {"BBB": "United States"})


def test_fifteen_highest_scores_and_three_a_sector() -> None:
    sectors = ["Tech"] * 6 + ["S1", "S1", "S2", "S2", "S3", "S3", "S4", "S4", "S5", "S5", "S6",
                              "S6"]
    rows = [row(f"N{i}", score=95.0 - i, sector=s) for i, s in enumerate(sectors)]
    good = {f"N{i}": {"f0": 20, "f1": 20, "f2": 20, "analysts": 5} for i in range(len(rows))}

    picks, pool = select(rows, good, {f"N{i}": "United States" for i in range(len(rows))})

    assert len(picks) == 15 and pool == 18
    assert sum(1 for i in range(6) if f"N{i}" in picks) == 3
    assert list(picks)[0] == "N0"


def test_the_screen_reads_percentages_and_skips_bad_rows(tmp_path: Path) -> None:
    path = tmp_path / "z.csv"
    path.write_text("ticker,f0,f1,f2,analysts\nBRK.B,20,30,40,5\nBAD,NA,30,40,5\n", "utf-8")

    assert read_screen(path) == {"BRK-B": {"f0": 20.0, "f1": 30.0, "f2": 40.0, "analysts": 5.0}}


def test_a_short_list_is_refused_rather_than_filled_with_anything(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        add_rebalance({"AAA": 80.0}, 1, "2026-11-30", "2026-09-30", "Sep 26", tmp_path / "b.json")


def test_a_recorded_date_cannot_be_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    picks = {f"N{i}": 80.0 for i in range(15)}
    add_rebalance(picks, 20, "2026-11-30", "2026-09-30", "Sep 26", path)

    with pytest.raises(ValueError):
        add_rebalance(picks, 20, "2026-11-30", "2026-09-30", "Sep 26", path)
    assert [s["trade_on"] for s in load_book(path)] == ["2026-11-30"]


def test_no_file_leaves_the_ledger_as_it_was(tmp_path: Path) -> None:
    assert load_book(tmp_path / "absent.json") == []


class Prices:
    def __init__(self, table: dict[str, dict[str, float]]) -> None:
        self.table = table

    def series(self, symbol: str) -> dict[str, float]:
        return self.table.get(symbol, {})

    def on_or_after(self, symbol: str, when: str):
        days = sorted(d for d in self.table.get(symbol, {}) if d >= when)
        return (days[0], self.table[symbol][days[0]]) if days else None

    def ret(self, symbol: str, start: str, end: str):
        a, b = self.on_or_after(symbol, start), self.on_or_after(symbol, end)
        return b[1] / a[1] - 1.0 if a and b and a[0] < b[0] else None


def ledger(book: list[dict], extra: dict | None = None) -> dict:
    hist = [("2025-12-31", 90.0), ("2026-03-31", 90.0)]
    names = ["OLD", "NEW"] + [f"P{i}" for i in range(40)]
    rows = [{"symbol": s, "name": s, "region": "us", "sector": s,
             "score_history": [90.0 - i * .1 for _ in hist],
             "score_history_dates": [d for d, _ in hist]} for i, s in enumerate(names)]
    days = {"2026-02-27": 10.0, "2026-06-01": 11.0, "2026-11-06": 12.0, "2026-11-09": 13.0}
    prices = {s: dict(days) for s in names}
    prices.update(extra or {})
    return build_region(rows, "us", Prices(prices), 1, 0, book=book)


def test_the_book_takes_over_from_the_old_rule() -> None:
    step = {"trade_on": "2026-11-06", "results_for": "2026-06-30", "label": "Nov 26 start",
            "pool": 58, "picks": {"NEW": 80.0}}

    market = ledger([step])

    assert [p["symbol"] for p in market["open_positions"]] == ["NEW"]
    assert market["open_positions"][0]["entry_date"] == "2026-11-06"
    last = market["quarters"][-1]
    assert last["quarter"] == "Nov 26 start" and last["universe"] == 58
    assert [e["symbol"] for e in last["exits"]] == ["OLD"]
    assert last["exits"][0]["exit_price"] == 12.0
    assert last["period_from"] is not None


def test_a_step_with_no_closing_price_yet_waits() -> None:
    step = {"trade_on": "2026-11-06", "results_for": "2026-06-30", "label": "Nov 26 start",
            "pool": 58, "picks": {"NEW": 80.0}}
    early = {"NEW": {"2026-02-27": 10.0, "2026-06-01": 11.0}}

    market = ledger([step], early)

    assert [p["symbol"] for p in market["open_positions"]] == ["OLD"]


def test_the_book_does_not_touch_other_markets(monkeypatch) -> None:
    assert rebalance_ledger.HOLD_BUFFER_BY_REGION == {"us": 30}
    assert us_book.SIZE == 15


def test_a_name_with_no_chart_cannot_be_bought() -> None:
    assert not qualifies({**row("AAA"), "technical_as_of": None}, screen(), HOME)
