"""The ledger's pairing: a position is bought once, sold once, and priced at both ends."""

from __future__ import annotations

from app.ingestion.rebalance_ledger import build_region, capped_picks


class FakePrices:
    """Closes we control, so the arithmetic is checkable rather than plausible."""

    def __init__(self, table: dict[str, dict[str, float]]) -> None:
        self.table = table

    def series(self, symbol: str) -> dict[str, float]:
        return self.table.get(symbol, {})

    def on_or_after(self, symbol: str, when: str):
        days = sorted(d for d in self.table.get(symbol, {}) if d >= when)
        return (days[0], self.table[symbol][days[0]]) if days else None

    def ret(self, symbol: str, start: str, end: str):
        """Return between two dates - what the quarterly portfolio figure is built from."""
        a = self.on_or_after(symbol, start)
        b = self.on_or_after(symbol, end)
        if not a or not b or a[0] >= b[0] or a[1] <= 0:
            return None
        return b[1] / a[1] - 1.0


def _rows(history: dict[str, list[tuple[str, float]]]) -> list[dict]:
    out = []
    for symbol, points in history.items():
        out.append({
            "symbol": symbol, "name": symbol, "region": "psx", "sector": "Cement",
            "score_history": [s for _, s in points],
            "score_history_dates": [d for d, _ in points],
        })
    return out


def test_a_position_is_bought_once_and_sold_when_it_drops_out() -> None:
    # Two quarter-ends. WINNER holds its place; LOSER is displaced by RISER in the second.
    # Padding takes the universe past the minimum, so a top-2 is a real selection.
    hist = {
        "WINNER": [("2025-12-31", 90.0), ("2026-03-31", 92.0)],
        "LOSER": [("2025-12-31", 80.0), ("2026-03-31", 10.0)],
        "RISER": [("2025-12-31", 5.0), ("2026-03-31", 85.0)],
    }
    for i in range(40):
        hist[f"PAD{i}"] = [("2025-12-31", 1.0), ("2026-03-31", 1.0)]

    prices = FakePrices({
        # Bought 2 months after 31 Dec -> 28 Feb; sold 2 months after 31 Mar -> 31 May.
        "LOSER": {"2026-02-28": 100.0, "2026-05-31": 125.0},
        "WINNER": {"2026-02-28": 50.0, "2026-05-31": 60.0, "2026-07-01": 66.0},
        "RISER": {"2026-05-31": 20.0, "2026-07-01": 22.0},
    })
    led = build_region(_rows(hist), "psx", prices, top_n=2, quarters=1)

    # The reported quarter is the SECOND boundary: the first only opens positions.
    assert len(led["quarters"]) == 1
    q = led["quarters"][0]
    assert q["quarter"] == "Mar 26"

    exits = {e["symbol"]: e for e in q["exits"]}
    assert set(exits) == {"LOSER"}
    sold = exits["LOSER"]
    assert sold["entry_price"] == 100.0
    assert sold["exit_price"] == 125.0
    assert sold["return_pct"] == 25.0          # bought 100, sold 125
    assert sold["entry_quarter"] == "Dec 25"   # entered on the PREVIOUS quarter's results

    # RISER joined at this rebalance and is still open, so it is not a realised trade.
    assert {e["symbol"] for e in q["entries"]} == {"RISER"}
    assert led["realised_trades"] == 1
    assert led["realised_avg_return_pct"] == 25.0


def test_a_name_that_never_leaves_stays_open_and_unrealised() -> None:
    """A holding still in the top 20 has no exit price, and must not be counted as a result."""
    hist = {"WINNER": [("2025-12-31", 90.0), ("2026-03-31", 92.0)]}
    for i in range(40):
        hist[f"PAD{i}"] = [("2025-12-31", 1.0), ("2026-03-31", 1.0)]
    prices = FakePrices({"WINNER": {"2026-02-28": 50.0, "2026-07-01": 75.0}})

    led = build_region(_rows(hist), "psx", prices, top_n=1, quarters=1)
    assert led["realised_trades"] == 0
    open_now = {r["symbol"]: r for r in led["open_positions"]}
    assert "WINNER" in open_now
    assert open_now["WINNER"]["entry_price"] == 50.0
    assert open_now["WINNER"]["return_pct"] == 50.0     # marked to the newest close
    assert open_now["WINNER"]["open"] is True


def test_entry_price_is_the_first_close_that_actually_traded() -> None:
    """The rebalance date may be a holiday. The fill is the next real close, not a gap."""
    # A leads on Dec-25 results, then B overtakes it on Mar-26 - so A is sold.
    hist = {"A": [("2025-12-31", 90.0), ("2026-03-31", 5.0)],
            "B": [("2025-12-31", 2.0), ("2026-03-31", 80.0)]}
    for i in range(40):
        hist[f"PAD{i}"] = [("2025-12-31", 1.0), ("2026-03-31", 1.0)]
    # Nothing on 28 Feb; the market next trades on 4 March.
    prices = FakePrices({"A": {"2026-03-04": 200.0, "2026-06-02": 180.0},
                         "B": {"2026-06-02": 30.0}})

    led = build_region(_rows(hist), "psx", prices, top_n=1, quarters=1)
    sold = led["quarters"][0]["exits"][0]
    assert sold["entry_date"] == "2026-03-04"
    assert sold["entry_price"] == 200.0
    assert sold["return_pct"] == -10.0


def test_a_market_with_no_history_renders_empty_rather_than_breaking() -> None:
    led = build_region([], "gcc", FakePrices({}))
    assert led["quarters"] == []
    assert led["realised_trades"] == 0
    # Saudi only. The region KEY stays "gcc" - it is written into every snapshot and every
    # OHLC path - but the label has to say what is in it, now that Dubai is a separate market
    # sitting beside it and "GCC" would read as covering both.
    assert led["label"] == "Saudi (Tadawul)"


def test_no_sector_fills_more_than_its_share() -> None:
    """Fifteen slots hold three of a sector, however well the fourth scores."""
    ranked = [(f"BANK{i}", 99.0 - i) for i in range(10)]
    for n, sector in enumerate(("TECH", "MINE", "FOOD", "AUTO")):
        ranked += [(f"{sector}{i}", 50.0 - n - i) for i in range(3)]
    names = {s: {"sector": "Financial Services" if s.startswith("BANK") else s[:4]}
             for s, _ in ranked}

    picks = capped_picks(ranked, names, 15)

    assert len(picks) == 15
    assert sum(s.startswith("BANK") for s in picks) == 3
    assert {f"BANK{i}" for i in range(3)} <= picks


def test_pakistan_banks_and_insurers_count_as_one_sector() -> None:
    ranked = [("BANK", 90.0), ("INSURER", 89.0), ("INVEST", 88.0), ("CEMENT", 87.0),
              ("SUGAR", 86.0)]
    names = {"BANK": {"sector": "Commercial Banks"}, "INSURER": {"sector": "Insurance"},
             "INVEST": {"sector": "Inv. Banks / Inv. Cos. / Securities Cos."},
             "CEMENT": {"sector": "Cement"}, "SUGAR": {"sector": "Sugar & Allied Industries"}}

    picks = capped_picks(ranked, names, 3, share=0.40)

    assert picks == {"BANK", "CEMENT", "SUGAR"}


def test_a_market_too_narrow_for_the_cap_still_fills_the_portfolio() -> None:
    ranked = [(f"BANK{i}", 99.0 - i) for i in range(5)]
    names = {s: {"sector": "Financial Services"} for s, _ in ranked}

    assert capped_picks(ranked, names, 4) == {"BANK0", "BANK1", "BANK2", "BANK3"}


def test_a_company_with_no_sector_is_not_capped() -> None:
    ranked = [(f"X{i}", 99.0 - i) for i in range(5)]

    assert len(capped_picks(ranked, {}, 5)) == 5


def _two_quarters() -> tuple[dict, FakePrices]:
    hist = {
        "OLD": [("2025-12-31", 90.0), ("2026-03-31", 80.0)],
        "NEW": [("2025-12-31", 10.0), ("2026-03-31", 95.0)],
    }
    for i in range(40):
        hist[f"PAD{i}"] = [("2025-12-31", 1.0), ("2026-03-31", 1.0)]
    return hist, FakePrices({"OLD": {"2026-02-28": 100.0, "2026-05-31": 120.0},
                             "NEW": {"2026-02-28": 50.0, "2026-05-31": 55.0}})


def test_a_recorded_rebalance_survives_its_scores_rolling_out_of_history() -> None:
    """Twenty quarters per company, so each new result takes the oldest one away."""
    hist, prices = _two_quarters()
    first = build_region(_rows(hist), "psx", prices, top_n=1)
    rolled = {symbol: points[1:] for symbol, points in hist.items()}

    again = build_region(_rows(rolled), "psx", prices, top_n=1, locks=first["locked"])

    assert again["quarters"] == first["quarters"]
    assert again["open_positions"] == first["open_positions"]
    assert again["locked"] == first["locked"]


def test_a_later_change_of_score_does_not_change_what_was_bought() -> None:
    hist, prices = _two_quarters()
    first = build_region(_rows(hist), "psx", prices, top_n=1)
    hist["NEW"] = [("2025-12-31", 99.0), ("2026-03-31", 95.0)]

    again = build_region(_rows(hist), "psx", prices, top_n=1, locks=first["locked"])

    assert list(again["locked"]["2025-12-31"]["picks"]) == ["OLD"]
    assert again["quarters"][0]["exits"][0]["symbol"] == "OLD"


def test_a_repaired_price_still_reaches_a_locked_quarter() -> None:
    hist, prices = _two_quarters()
    first = build_region(_rows(hist), "psx", prices, top_n=1)
    prices.table["OLD"]["2026-05-31"] = 150.0

    again = build_region(_rows(hist), "psx", prices, top_n=1, locks=first["locked"])

    assert again["quarters"][0]["portfolio_return_pct"] == 50.0


def test_a_short_book_is_not_locked() -> None:
    """A missing input on one run must not become the record."""
    hist, prices = _two_quarters()

    led = build_region(_rows(hist), "psx", prices, top_n=1,
                       narrow=lambda ranked, quarter, day: [])

    assert led["locked"] == {}


def test_the_record_opens_on_the_market_start() -> None:
    hist, prices = _two_quarters()
    for points in hist.values():
        points.insert(0, ("2025-09-30", 50.0))
    for table in prices.table.values():
        table["2025-11-30"] = 100.0

    led = build_region(_rows(hist), "psx", prices, top_n=1, start="2025-12-31")

    assert led["first_quarter"] == "Mar 26"
    assert sorted(led["locked"]) == ["2025-12-31", "2026-03-31"]
