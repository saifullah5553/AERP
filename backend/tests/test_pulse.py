from __future__ import annotations

from app.services.pulse import pulse_from_pairs, pulse_from_screener_dicts


def test_pulse_labels_and_breadth() -> None:
    pairs = [
        ("us", 80.0), ("us", 70.0), ("us", 65.0),   # avg 71.7 → bullish
        ("psx", 30.0), ("psx", 35.0),               # avg 32.5 → bearish
        ("india", 50.0), ("india", 52.0),           # avg 51 → neutral
    ]
    out = {r["region"]: r for r in pulse_from_pairs(pairs)}
    assert out["us"]["pulse"] == "bullish"
    assert out["us"]["bullish"] == 3
    assert out["psx"]["pulse"] == "bearish"
    assert out["psx"]["bearish"] == 2
    assert out["india"]["pulse"] == "neutral"
    assert out["india"]["count"] == 2


def test_pulse_ignores_none_and_empty() -> None:
    out = pulse_from_pairs([("us", None), ("us", 60.0)])
    assert len(out) == 1 and out[0]["count"] == 1
    assert pulse_from_pairs([]) == []


def test_pulse_from_screener_dicts_reads_region_string() -> None:
    rows = [
        {"region": "gcc", "composite_score": 62.0},
        {"region": "gcc", "composite_score": 58.0},
        {"region": "us", "composite_score": None},
    ]
    out = {r["region"]: r for r in pulse_from_screener_dicts(rows)}
    assert out["gcc"]["count"] == 2
    assert "us" not in out  # only a None composite → excluded


def test_pulse_region_ordering() -> None:
    pairs = [("global", 50.0), ("us", 50.0), ("psx", 50.0)]
    regions = [r["region"] for r in pulse_from_pairs(pairs)]
    assert regions == ["us", "psx", "global"]  # fixed display order
