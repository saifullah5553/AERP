from __future__ import annotations

from app.engines.composite.signals import derive_signal
from app.models.enums import SignalType

COMPONENTS = {"fundamental": 80.0, "technical": 70.0}


def test_thresholds() -> None:
    assert derive_signal(85, 1.0, COMPONENTS).signal == SignalType.STRONG_BUY
    assert derive_signal(70, 1.0, COMPONENTS).signal == SignalType.BUY
    assert derive_signal(50, 1.0, COMPONENTS).signal == SignalType.HOLD
    assert derive_signal(35, 1.0, COMPONENTS).signal == SignalType.SELL
    assert derive_signal(10, 1.0, COMPONENTS).signal == SignalType.STRONG_SELL


def test_confidence_scales_with_coverage() -> None:
    high = derive_signal(90, 1.0, COMPONENTS).confidence
    low = derive_signal(90, 0.5, COMPONENTS).confidence
    assert high > low


def test_rationale_names_drivers() -> None:
    result = derive_signal(85, 1.0, COMPONENTS)
    assert "Strong Buy" in result.rationale
    assert "fundamental" in result.rationale
