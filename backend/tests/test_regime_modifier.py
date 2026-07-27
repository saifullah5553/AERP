from __future__ import annotations

from app.engines.composite.regime_modifier import MAX_TOTAL, apply_regime_modifier


def _regime(health, rate_cycle=None, label="Neutral"):
    signals = []
    if rate_cycle is not None:
        signals.append({"key": "rate_cycle", "label": "Rate cycle", "score": rate_cycle})
    return {"regime": label, "health": health, "signals": signals}


def test_no_regime_is_noop() -> None:
    assert apply_regime_modifier(60.0, None, 1.0) == (60.0, {})
    assert apply_regime_modifier(60.0, {"health": None, "signals": []}, 1.0) == (60.0, {})


def test_bullish_regime_lifts_and_bearish_lowers() -> None:
    up, bd_up = apply_regime_modifier(60.0, _regime(90, label="Bullish"), None)
    down, bd_down = apply_regime_modifier(60.0, _regime(10, label="Bearish"), None)
    assert up > 60.0 and bd_up["health_tilt"] > 0
    assert down < 60.0 and bd_down["health_tilt"] < 0
    assert "rate_leverage" not in bd_up  # no D/E given


def test_rate_leverage_interaction() -> None:
    # Falling rates (high rate_cycle score) + high leverage → tailwind.
    fall, bd_f = apply_regime_modifier(60.0, _regime(50, rate_cycle=80), 1.5)
    # Rising rates (low score) + high leverage → penalty.
    rise, bd_r = apply_regime_modifier(60.0, _regime(50, rate_cycle=20), 1.5)
    assert bd_f["rate_leverage"] > 0 and fall > 60.0
    assert bd_r["rate_leverage"] < 0 and rise < 60.0


def test_low_leverage_no_rate_leg() -> None:
    _, bd = apply_regime_modifier(60.0, _regime(50, rate_cycle=20), 0.5)
    assert "rate_leverage" not in bd


def test_total_is_clamped() -> None:
    adj, bd = apply_regime_modifier(60.0, _regime(100, rate_cycle=100), 5.0)
    assert bd["total"] <= MAX_TOTAL
    assert adj <= 60.0 + MAX_TOTAL


def test_result_stays_in_bounds() -> None:
    adj, _ = apply_regime_modifier(98.0, _regime(100, rate_cycle=100), 5.0)
    assert 0.0 <= adj <= 100.0
    assert apply_regime_modifier(None, _regime(90), 1.0) == (None, {})
