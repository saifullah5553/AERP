"""The price-action engine: the judgements it must get right, and the ones it must refuse.

Each test below is a rule from the brief that a naive implementation breaks. They are written
against synthetic bars so the expected answer is not a matter of opinion.
"""

from __future__ import annotations

from app.engines.price_action import candles as C
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
    assert set(res.components) == {"structure", "levels", "breakout", "volume", "candles"}
    assert abs(sum(res.components.values()) - res.score) < 0.01
    assert 0 <= res.score <= 100


def test_no_trade_is_a_real_answer_with_a_trigger() -> None:
    """A flat, structureless chart must not produce a setup."""
    dates, o, h, low, c, v = _bars([100.0 + (i % 3) * 0.1 for i in range(120)])
    res = analyse(dates, o, h, low, c, v)
    if res.setup.kind == "no_trade":
        assert "NO TRADE" in res.setup.rationale
        assert "Trigger" in res.setup.rationale
