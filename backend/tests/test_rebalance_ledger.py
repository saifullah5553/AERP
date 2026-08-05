"""The ledger's pairing: a position is bought once, sold once, and priced at both ends."""

from __future__ import annotations

from app.ingestion.rebalance_ledger import build_region


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
    assert led["label"] == "GCC"
