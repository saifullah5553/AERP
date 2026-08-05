

def test_a_split_rebases_the_whole_stored_history(tmp_path) -> None:
    """A 5:1 split re-issues the entire series divided by five. We must follow it.

    Keeping stored days as first written left raw prices before the split and adjusted ones
    after, so a holding bought pre-split and sold post-split showed a ~80% loss that never
    happened. KOHC split 5/1 in Aug 2025; the ledger reported -73%.
    """
    from app.ingestion.ohlc_store import load_bars, save_bars

    old = [{"date": f"2025-08-{d:02d}", "open": 500.0, "high": 505.0, "low": 495.0,
            "close": 500.0, "volume": 1000} for d in (1, 4, 5, 6, 7)]
    save_bars("psx", "KOHC", old, store=tmp_path)

    # The vendor now returns the same days at a fifth of the price, plus new ones.
    adjusted = [{"date": f"2025-08-{d:02d}", "open": 100.0, "high": 101.0, "low": 99.0,
                 "close": 100.0, "volume": 5000} for d in (4, 5, 6, 7)]
    adjusted.append({"date": "2025-08-26", "open": 102.0, "high": 103.0, "low": 101.0,
                     "close": 102.0, "volume": 5100})
    save_bars("psx", "KOHC", adjusted, store=tmp_path)

    bars = load_bars("psx", "KOHC", store=tmp_path)
    # The day that existed ONLY in the old file must have been re-based too - that is the day
    # a pre-split purchase would have been priced at.
    assert abs(float(bars["2025-08-01"][4]) - 100.0) < 0.01
    assert abs(float(bars["2025-08-26"][4]) - 102.0) < 0.01
    # ...and no cliff is left anywhere in the series.
    closes = [float(bars[d][4]) for d in sorted(bars)]
    for a, b in zip(closes, closes[1:], strict=False):
        assert 0.5 < a / b < 2.0, "a split-sized gap survived the merge"


def test_ordinary_prices_are_not_mistaken_for_a_split(tmp_path) -> None:
    """A real 30% fall is a fall. Re-basing history off it would erase the loss."""
    from app.ingestion.ohlc_store import load_bars, save_bars

    save_bars("psx", "FALL", [{"date": f"2025-08-{d:02d}", "open": 100.0, "high": 100.0,
                               "low": 100.0, "close": 100.0, "volume": 10}
                              for d in (1, 4, 5, 6)], store=tmp_path)
    save_bars("psx", "FALL", [{"date": "2025-08-07", "open": 70.0, "high": 70.0,
                               "low": 70.0, "close": 70.0, "volume": 10}], store=tmp_path)
    bars = load_bars("psx", "FALL", store=tmp_path)
    assert abs(float(bars["2025-08-01"][4]) - 100.0) < 0.01   # untouched
    assert abs(float(bars["2025-08-07"][4]) - 70.0) < 0.01


def test_a_duplicated_split_resolves_to_the_later_date() -> None:
    """Yahoo reports these twice; the ex-date is the second one.

    KOHC 5:1 came through as 21 and 25 Aug 2025 (actual: 25 Aug), KTML 5:1 as 11 and 15 Sep
    (actual: 15 Sep). Taking the earlier date divides the days in between, which were still
    trading on the old basis.
    """
    from app.ingestion.split_adjust import parse_splits

    events = {"splits": {
        "a": {"date": 1757565000, "numerator": 5.0, "denominator": 1.0},   # 11 Sep 2025
        "b": {"date": 1757910600, "numerator": 5.0, "denominator": 1.0},   # 15 Sep 2025
    }}
    assert parse_splits(events) == [("2025-09-15", 5.0)]


def test_two_genuine_splits_are_not_collapsed() -> None:
    """Far apart, or a different ratio, means two corporate actions - keep both."""
    from app.ingestion.split_adjust import parse_splits

    events = {"splits": {
        "a": {"date": 1757565000, "numerator": 5.0, "denominator": 1.0},   # Sep 2025
        "b": {"date": 1788928200, "numerator": 2.0, "denominator": 1.0},   # a year later
    }}
    assert len(parse_splits(events)) == 2
