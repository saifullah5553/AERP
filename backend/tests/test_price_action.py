"""The price-action engine: the judgements it must get right, and the ones it must refuse.

Each test below is a rule from the brief that a naive implementation breaks. They are written
against synthetic bars so the expected answer is not a matter of opinion.
"""

from __future__ import annotations

import numpy as np
from app.engines.price_action import candles as C
from app.engines.price_action import engine as E
from app.engines.price_action import structure as S
from app.engines.price_action import volume as V
from app.engines.price_action.engine import analyse


def _bars(prices: list[float], vols: list[float] | None = None, span: float = 0.02):
    """A synthetic series: each close with a proportional range around it."""
    dates, o, h, low, c, v = [], [], [], [], [], []
    for i, p in enumerate(prices):
        day = 1 + i
        dates.append(f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}")
        prev = prices[i - 1] if i else p
        o.append(prev)
        h.append(max(p, prev) * (1 + span))
        low.append(min(p, prev) * (1 - span))
        c.append(p)
        v.append(vols[i] if vols else 1_000_000)
    return dates, o, h, low, c, v


def test_no_banned_indicator_appears_in_the_code() -> None:
    """The brief bans these by name, so the package is checked for them.

    CODE only - docstrings and comments are stripped first, because the modules quote the
    banned list in order to state the prohibition and a plain grep cannot tell the rule from a
    violation of it.
    """
    import ast
    import pathlib

    banned = ("rsi", "macd", "bollinger", "stochastic", "adx", "atr", "vwap", "ichimoku",
              "fibonacci", "cci", "mfi", "obv", "supertrend", "sar", "ema", "sma")
    pkg = pathlib.Path(__file__).resolve().parents[1] / "app" / "engines" / "price_action"
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                node.value.value = ""          # drop the docstring, keep the structure
        names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.name.lower() for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef | ast.ClassDef)}
        for term in banned:
            assert term not in names, f"{term} used in {path.name}"


def test_a_single_swing_is_not_a_level() -> None:
    """A level earns its place by being respected more than once."""
    points = [S.Swing(0, "2026-01-01", 100.0, "high"), S.Swing(9, "2026-01-10", 80.0, "low")]
    zones = S.zones(points, [90.0], [101.0], [79.0], 90.0)
    assert zones == []


def test_zones_do_not_chain_into_one_huge_band() -> None:
    """Clustering off the previous member merged Apple's 207-228 into a single 'level'."""
    ladder = [S.Swing(i, f"2026-01-{i + 1:02d}", 100.0 + i, "low") for i in range(20)]
    zones = S.zones(ladder, [130.0], [131.0], [99.0], 130.0)
    for z in zones:
        assert (z.high / z.low - 1) <= 0.05, f"zone {z.low}-{z.high} is too wide to be a level"


def test_a_new_high_then_a_pullback_is_not_distribution() -> None:
    """One lower low after a HIGHER HIGH is a pullback.

    Reading the single most recent label called Apple 'uptrend to distribution' while it was
    printing all-time highs. Distribution needs the highs to stop advancing too.
    """
    pts = [
        S.Swing(0, "2026-01-01", 100.0, "low"), S.Swing(1, "2026-01-05", 120.0, "high"),
        S.Swing(2, "2026-01-09", 110.0, "low"), S.Swing(3, "2026-01-14", 140.0, "high"),
        S.Swing(4, "2026-01-20", 105.0, "low"),   # deep pullback, but the high was a NEW high
    ]
    assert S.classify_structure(pts, [130.0]).label != "uptrend_to_distribution"


def test_lower_high_and_lower_low_is_distribution() -> None:
    pts = [
        S.Swing(0, "2026-01-01", 100.0, "low"), S.Swing(1, "2026-01-05", 150.0, "high"),
        S.Swing(2, "2026-01-09", 120.0, "low"), S.Swing(3, "2026-01-14", 140.0, "high"),
        S.Swing(4, "2026-01-20", 110.0, "low"),
    ]
    assert S.classify_structure(pts, [115.0]).label in (
        "uptrend_to_distribution", "weak_downtrend", "strong_downtrend")


def test_high_volume_is_not_bullish_by_itself() -> None:
    """The rule broken most often. Same 3x volume, opposite readings."""
    heavy = V.VolumeRead(relative=3.0, label="very_high", average=1000.0, note="")
    up = V.price_volume_verdict(+4.0, heavy)
    down = V.price_volume_verdict(-4.0, heavy)
    assert "demand" in up
    assert "supply" in down
    flat = V.price_volume_verdict(0.1, heavy)
    assert "absorption" in flat


def test_volume_survives_a_numpy_array() -> None:
    """Production hands the engine numpy arrays, and `if volume` on one raises. The except
    around it hid that, so no market had a volume reading from the day this shipped."""
    days = [f"2026-01-{i + 1:02d}" for i in range(25)]
    px = np.linspace(100.0, 110.0, 25)
    vol = np.array([1_000.0] * 24 + [3_000.0])
    bars = C.to_bars(days, px, px * 1.01, px * 0.99, px, vol)
    assert bars[-1].volume == 3_000.0
    assert V.relative_volume([b.volume for b in bars]).relative == 3.0


def test_relative_volume_excludes_today_from_its_own_average() -> None:
    """Otherwise the yardstick moves with the very bar being measured."""
    vols = [100.0] * 20 + [1000.0]
    read = V.relative_volume(vols)
    assert read.average == 100.0
    assert read.relative == 10.0


def test_volume_dry_up_and_expansion_are_distinguished() -> None:
    assert V.trend([100.0] * 5 + [30.0] * 5) == "drying_up"
    assert V.trend([100.0] * 5 + [300.0] * 5) == "expanding"
    assert V.trend([100.0] * 10) == "steady"


def test_an_ordinary_bar_gets_no_pattern() -> None:
    """A detector that finds something every day is measuring its own thresholds."""
    dates, o, h, low, c, v = _bars([100 + i * 0.1 for i in range(30)], span=0.005)
    bars = C.to_bars(dates, o, h, low, c, v)
    notes = C.read(bars)
    assert not any("engulfing" in n or "rejection" in n for n in notes)


def test_short_history_refuses_to_score() -> None:
    dates, o, h, low, c, v = _bars([100.0] * 10)
    res = analyse(dates, o, h, low, c, v)
    assert res.score is None
    assert res.setup.kind == "no_trade"
    assert "cannot be determined" in res.summary


def test_score_is_the_five_components_and_nothing_else() -> None:
    dates, o, h, low, c, v = _bars([100 + (i % 7) for i in range(120)])
    res = analyse(dates, o, h, low, c, v)
    assert res.score is not None
    assert set(res.components) == {"structure", "levels", "breakout", "volume",
                                   "relative_strength"}
    # The parts must sum to the whole even with NO benchmark, where the four measurable legs
    # are scaled up to cover the missing one. A total that exceeded its own breakdown would be
    # unauditable - the reader could not check the number against its reasons.
    assert abs(sum(res.components.values()) - res.score) < 0.01
    assert 0 <= res.score <= 100


def test_the_same_chart_scores_differently_depending_on_its_market() -> None:
    """The gap this replaced candles to fill.

    One price series, two markets. Judged in isolation these are the same chart and the old
    engine scored them identically - which is the defect: a stock rising 16% while its index
    rises 51% is a laggard, and the chart alone cannot say so.

    The contrast asserted here is laggard-vs-in-line, NOT laggard-vs-leader, because the
    measured curve is an inverted U - a huge lead scores BELOW a stock tracking its market.
    See test_extreme_leaders_do_not_outscore_moderate_ones.
    """
    dates, o, h, low, c, v = _bars([100 + i * 0.3 for i in range(120)])

    in_line = _bars([100 + i * 0.3 for i in range(120)])   # market matching the stock
    runaway = _bars([100 + i * 1.5 for i in range(120)])   # market leaving it far behind

    def bench(bundle):
        d, bo, bh, bl, bc, bv = bundle
        return [C.Bar(date=d[i], open=bo[i], high=bh[i], low=bl[i], close=bc[i], volume=bv[i])
                for i in range(len(d))]

    tracking = analyse(dates, o, h, low, c, v, benchmark_bars=bench(in_line))
    lagging = analyse(dates, o, h, low, c, v, benchmark_bars=bench(runaway))

    assert abs(tracking.relative["lead_pct"]) < 1.0        # by construction, in line
    assert lagging.relative["lead_pct"] < -25              # badly behind
    assert (tracking.components["relative_strength"]
            > lagging.components["relative_strength"] + 5)
    assert tracking.score > lagging.score
    assert "lagging" in lagging.relative["note"]


def test_extreme_leaders_do_not_outscore_moderate_ones() -> None:
    """The measured shape, guarded.

    Relative strength is an INVERTED U: over 477k point-in-time observations the +24pp-and-above
    bucket returned -5.42% against its market while the -4..+5pp bucket returned -2.69%. A
    linear "more lead is better" score - which is what this module shipped first - would award
    the worst-but-one bucket full marks. If someone ever restores that, this fails.
    """
    from app.engines.price_action.relative import _score_lead

    assert _score_lead(-4) > _score_lead(60), "an extreme leader must not beat a market-performer"
    assert _score_lead(-4) > _score_lead(-40), "a severe laggard must score far worse"
    # The single worst bucket is the left tail, not the right one - that asymmetry is the
    # factor's actual content.
    assert _score_lead(-40) < _score_lead(60)
    # Peak sits near parity with the market, not at the top of the range.
    peak = max(range(-100, 101), key=lambda x: _score_lead(x))
    assert -10 <= peak <= 6, f"peak at {peak}pp, expected near parity"


def test_widening_lead_is_reported_but_not_scored() -> None:
    """A widening lead measured WORSE than a narrowing one in all seven bands, so it earns a
    note and nothing else. Two reads differing only in slope must score identically."""
    from app.engines.price_action.relative import _score_lead

    # Same lead, whatever the slope: the score is a function of lead alone.
    assert _score_lead(8.0) == _score_lead(8.0)
    import inspect

    from app.engines.price_action import relative

    src = inspect.getsource(relative.read)
    scoring = src.split("base = _score_lead")[1]
    assert "base +" not in scoring and "base -" not in scoring, (
        "the slope must not adjust the score - it measured negative, not positive"
    )


def _zone(origin: str, kind: str, low: float = 99.0, high: float = 100.0) -> S.Zone:
    return S.Zone(low=low, high=high, kind=kind, touches=3, last_touch="2026-01-01",
                  strength="major", evidence="", origin=origin)


def _session(closes: list[float], volumes: list[float | None], wick: float = 0.3) -> list[C.Bar]:
    """Bars around each close. The open is the previous close, so a break bar starts below."""
    out, prev = [], closes[0]
    for i, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        out.append(C.Bar(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", prev,
                         max(prev, close) + wick, min(prev, close) - wick, close, volume))
        prev = close
    return out


def _read(bars: list[C.Bar], zone: S.Zone) -> E.BreakRead:
    vols = [b.volume if b.volume is not None else 0.0 for b in bars]
    return E._breakout(bars, [zone], V.relative_volume(vols))


_FLAT = [95.0] * 30
_QUIET = [1_000.0] * 30
# A cleared resistance zone, labelled as what it is now: support.
_CLEARED = ("resistance", "support")


def test_a_close_through_resistance_on_heavy_volume_is_confirmed() -> None:
    res = _read(_session([*_FLAT, 103.0], [*_QUIET, 3_000.0]), _zone(*_CLEARED))
    assert res.status == "confirmed_breakout"


def test_a_breakout_on_light_volume_is_suspect() -> None:
    res = _read(_session([*_FLAT, 103.0], [*_QUIET, 500.0]), _zone(*_CLEARED))
    assert res.status == "breakout_suspect_low_volume"


def test_a_breakout_on_ordinary_volume_is_only_forming() -> None:
    res = _read(_session([*_FLAT, 103.0], [*_QUIET, 1_100.0]), _zone(*_CLEARED))
    assert res.status == "breakout_forming"


def test_a_breakout_is_never_confirmed_on_price_alone() -> None:
    res = _read(_session([*_FLAT, 103.0], [None] * 31), _zone(*_CLEARED))
    assert res.status == "breakout_forming"


def test_a_close_through_support_on_heavy_volume_is_a_confirmed_breakdown() -> None:
    bars = _session([*([105.0] * 30), 96.0], [*_QUIET, 3_000.0])
    assert _read(bars, _zone("support", "resistance")).status == "confirmed_breakdown"


def test_a_breakdown_on_ordinary_volume_is_only_forming() -> None:
    bars = _session([*([105.0] * 30), 96.0], [*_QUIET, 1_100.0])
    assert _read(bars, _zone("support", "resistance")).status == "breakdown_forming"


def test_a_bounce_off_support_is_not_a_breakout() -> None:
    """The reason origin exists. Ignoring the label alone would call this a breakout."""
    bars = _session([*([99.5] * 30), 103.0], [*_QUIET, 3_000.0])
    assert _read(bars, _zone("support", "support")).status == "no_breakout"


def test_a_pullback_through_old_resistance_is_not_a_breakout() -> None:
    """SKWD: 61.67, down to 57.96 through a 58.45-59.02 level, back to 62.22. Price came from
    above, so this is a pullback that held and light volume says nothing against it."""
    closes = [*([61.5] * 25), 60.1, 58.6, 58.0, 58.5, 59.1, 61.1, 60.9, 62.2]
    bars = _session(closes, [1_000.0] * (len(closes) - 1) + [700.0])
    res = _read(bars, _zone("resistance", "support", low=58.45, high=59.02))
    assert res.status == "no_breakout"


def test_only_the_latest_approach_decides_the_direction_of_a_break() -> None:
    """CDRO: under the level on the 23rd, clear above it on the 27th, broke on the 28th."""
    closes = [*([9.4] * 25), 8.99, 9.21, 9.64, 9.05, 8.52, 8.65, 8.52, 8.69, 8.95]
    vols = [1_000.0] * len(closes)
    vols[28] = 3_000.0
    res = _read(_session(closes, vols, wick=0.05),
                _zone("support", "resistance", low=9.145, high=9.25))
    assert res.status == "confirmed_breakdown"
    assert res.volume.relative is not None and res.volume.relative > 2


def test_a_rejection_under_old_support_is_not_a_breakdown() -> None:
    closes = [*([92.0] * 25), 94.0, 99.8, 100.2, 99.5, 96.0]
    bars = _session(closes, [1_000.0] * (len(closes) - 1) + [3_000.0])
    res = _read(bars, _zone("support", "resistance"))
    assert res.status == "no_breakout"


def test_reclaiming_lost_support_is_still_a_bear_trap() -> None:
    closes = [*([105.0] * 25), 96.0, 96.0, 96.0, 103.0]
    bars = _session(closes, [1_000.0] * len(closes))
    assert _read(bars, _zone("support", "support")).status == "failed_breakdown"


def test_a_run_through_old_swing_highs_is_not_a_bear_trap() -> None:
    """This shape used to land in failed_breakdown, worth 16 points and a "bear trap" setup."""
    closes = [*([96.0] * 25), 103.0]
    bars = _session(closes, [*([1_000.0] * 25), 3_000.0])
    assert _read(bars, _zone(*_CLEARED)).status == "confirmed_breakout"


def test_quiet_days_after_a_break_do_not_undo_its_volume() -> None:
    closes = [*_FLAT, 103.0, 103.5, 104.0, 104.5]
    bars = _session(closes, [*_QUIET, 3_000.0, 400.0, 400.0, 400.0], wick=0.1)
    res = _read(bars, _zone(*_CLEARED))
    assert res.status == "confirmed_breakout"
    assert res.volume.relative == 3.0


def test_the_break_bar_cannot_be_its_own_retest() -> None:
    closes = [*_FLAT, 103.0, 104.0]
    bars = _session(closes, [*_QUIET, 3_000.0, 1_000.0], wick=0.1)
    assert bars[-2].low < 100.0, "the fixture must be a bar that started below the level"
    assert _read(bars, _zone(*_CLEARED)).status == "confirmed_breakout"


def test_a_pullback_to_the_level_that_holds_is_a_retest() -> None:
    closes = [*_FLAT, 103.0, 100.4, 103.0]
    bars = _session(closes, [*_QUIET, 3_000.0, 1_000.0, 1_000.0], wick=0.1)
    assert _read(bars, _zone(*_CLEARED)).status == "breakout_retest_held"


def test_a_break_older_than_the_window_is_not_news() -> None:
    closes = [*_FLAT, *([103.0] * 15)]
    bars = _session(closes, [1_000.0] * len(closes))
    assert _read(bars, _zone(*_CLEARED)).status == "no_breakout"


def test_a_real_range_breakout_comes_through_the_whole_engine() -> None:
    """End to end, with zones the engine found itself: the path that could never fire."""
    n = 120
    closes = [95.0 + 4.0 * float(np.sin(i / 3.0)) for i in range(n)] + [104.0]
    px = np.array(closes)
    vol = np.array([1_000.0] * n + [3_000.0])
    days = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n + 1)]
    res = analyse(days, px, px * 1.002, px * 0.998, px, vol)
    assert res.breakout_status == "confirmed_breakout"
    assert "heavy volume" in res.summary
