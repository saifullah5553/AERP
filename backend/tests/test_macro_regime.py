from __future__ import annotations

from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from app.services.macro_regime import Signal as _Signal
from app.services.macro_regime import (
    _direction,
    _score_falling_good,
    _synthesize,
    build_macro_regime,
)
from sqlalchemy.orm import Session


def test_direction_and_falling_good() -> None:
    assert _direction(10, 12) == "↓"
    assert _direction(12, 10) == "↑"
    assert _direction(10, 10) == "→"
    assert _score_falling_good(10, 12) == 80.0   # falling rate/inflation = supportive
    assert _score_falling_good(12, 10) == 30.0
    assert _score_falling_good(None, None) is None


def test_synthesize_weights_and_label() -> None:
    sigs = [
        _Signal("index_trend", "Index Trend", "up", 88.0),
        _Signal("rate_cycle", "Rate", "down", 80.0),
        _Signal("inflation_trend", "CPI", "down", 80.0),
    ]
    r = _synthesize("psx", sigs)
    assert r.regime == "Bullish" and r.health is not None and r.health >= 80
    assert "supportive" in r.explanation.lower()
    # a weak set → bearish
    weak = _synthesize("us", [_Signal("index_trend", "Index Trend", "down", 22.0),
                              _Signal("rate_cycle", "Rate", "up", 30.0)])
    assert weak.regime == "Bearish"


def test_pakistan_regime_from_series() -> None:
    # Falling rates + easing inflation + rising index → bullish PK regime, no DB needed.
    pk = {
        "kse100": [{"t": "2026-01-31", "v": 90000}, {"t": "2026-06-30", "v": 120000}],
        "sbp_policy_rate_pct": [{"t": "2025-12-31", "v": 15}, {"t": "2026-06-30", "v": 11}],
        "cpi_yoy_pct": [{"t": "2025-12-31", "v": 12}, {"t": "2026-06-30", "v": 5}],
        "usd_pkr": [{"t": "2025-12-31", "v": 280}, {"t": "2026-06-30", "v": 279}],
    }
    # empty DB (no non-PK data) — PK still resolves from the series
    out = build_macro_regime(_EmptyDB(), pk)  # type: ignore[arg-type]
    psx = out["countries"]["psx"]
    assert psx["regime"] == "Bullish"
    assert psx["health"] is not None
    keys = {s["key"] for s in psx["signals"]}
    assert {"index_trend", "rate_cycle", "inflation_trend"} <= keys


class _EmptyDB:
    """Minimal stand-in: every query returns nothing (PK path needs no DB)."""

    def scalar(self, *a, **k):
        return None

    def scalars(self, *a, **k):
        class _R:
            def all(self_inner):
                return []
        return _R()

    def get(self, *a, **k):
        return None


def test_build_with_db_regions(db: Session) -> None:
    db.add(Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US, country="US",
                  currency="USD", ticker_suffix=""))
    db.add(Security(market_id=1, symbol="AAPL", provider_symbol="AAPL",
                    asset_class=AssetClass.EQUITY, currency="USD"))
    db.commit()
    out = build_macro_regime(db, None)
    assert set(out["countries"]) >= {"psx", "us", "india", "gcc", "australia"}
    for c in out["countries"].values():
        assert c["regime"] in {"Bullish", "Neutral", "Bearish"}


def test_every_regime_index_is_actually_in_the_universe():
    """A market's index trend refreshes by looking its index ROW up in the snapshot. If the
    symbol is not in the curated universe there is no row, the lookup returns nothing, and the
    merge quietly keeps the last value written - no error, no blank, just a number that stops
    moving. PSX published a 26 Jul index reading for three weeks this way, and Dubai ran on
    breadth alone. The two lists have to agree, so assert it rather than hope."""
    from app.ingestion.universe_curated import INDICES
    from app.services.regime_snapshot import REGION_INDEX

    known = {symbol for symbol, _name in INDICES}
    missing = {
        region: symbol
        for region, symbol in REGION_INDEX.items()
        if symbol and symbol not in known
    }
    assert not missing, (
        f"regime indices absent from universe_curated.INDICES: {missing}. "
        "Their markets will silently freeze on the last index trend written."
    )
