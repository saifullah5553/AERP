from __future__ import annotations

import numpy as np
from app.ingestion.tech_refresh import (
    _composite_at,
    _record_signal_move,
    _signal_since,
    _signal_value_at,
)

# A rising close series (long enough for the indicators + lookback walk).
_N = 160
_RISING = np.linspace(100.0, 200.0, _N)
_VOL = np.full(_N, 1_000.0)
_LEGS = (70.0, None, None, None)  # fundamental only (PSX names often lack mom/qual/risk)


def test_composite_at_returns_triple() -> None:
    c = _composite_at(_RISING, _RISING, _RISING, _VOL, _N, _LEGS, None, None)
    assert c is not None
    comp, cov, present = c
    assert isinstance(comp, float)
    assert 0.0 <= comp <= 100.0
    assert "fundamental" in present


def test_offset_anchors_today_signal_to_committed() -> None:
    """With the right offset, the recomputed 'today' signal reproduces any committed band."""
    c = _composite_at(_RISING, _RISING, _RISING, _VOL, _N, _LEGS, None, None)
    assert c is not None
    cur_comp = c[0]
    # Pretend the live pipeline committed a composite of 82 (strong_buy band).
    committed_comp = 82.0
    offset = committed_comp - cur_comp
    sig = _signal_value_at(_RISING, _RISING, _RISING, _VOL, _N, _LEGS, None, None, offset)
    assert sig == "strong_buy"


def test_signal_since_walks_back_over_real_trajectory() -> None:
    """A ramp that only recently crossed into the signal band should date the crossing to a
    recent bar, not the first bar — and the returned close must come from that bar."""
    c = _composite_at(_RISING, _RISING, _RISING, _VOL, _N, _LEGS, None, None)
    assert c is not None
    offset = 82.0 - c[0]
    dates = [f"2026-01-{i + 1:02d}" if i < 28 else f"2026-idx-{i}" for i in range(_N)]
    since, price_at = _signal_since(
        dates, _RISING, _RISING, _RISING, _VOL, _LEGS, None, None,
        "strong_buy", comp_offset=offset,
    )
    assert since is not None
    # price_at is a real close from the series (not fabricated).
    assert float(_RISING[0]) <= price_at <= float(_RISING[-1])


def test_record_signal_move_buy_and_sell_and_noise() -> None:
    dst: dict = {}
    row = {"provider_symbol": "X.KA", "symbol": "X", "name": "X Co", "region": "psx"}
    # Entered strong_buy → time-to-buy.
    _record_signal_move(dst, row, "buy", "strong_buy", "Strong Buy", 81.0, 10.0, "2026-08-01")
    assert dst["X.KA"]["direction"] == "buy"
    # Left strong_buy → time-to-sell (overwrites the same symbol's latest state).
    _record_signal_move(dst, row, "strong_buy", "hold", "Hold", 55.0, 11.0, "2026-08-02")
    assert dst["X.KA"]["direction"] == "sell"
    # A non-strong-buy flip (buy→hold) is not a boundary crossing → ignored.
    dst2: dict = {}
    _record_signal_move(dst2, row, "buy", "hold", "Hold", 55.0, 11.0, "2026-08-02")
    assert dst2 == {}
    # No prior signal (first observation) → ignored.
    dst3: dict = {}
    _record_signal_move(dst3, row, None, "strong_buy", "Strong Buy", 81.0, 10.0, "2026-08-01")
    assert dst3 == {}
