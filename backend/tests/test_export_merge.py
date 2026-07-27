from __future__ import annotations

import json

from app.cli import _merge_regime, _merge_sector_stats, _regime_is_empty


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_regime_is_empty() -> None:
    assert _regime_is_empty(None)
    assert _regime_is_empty({"health": None, "signals": []})
    assert not _regime_is_empty({"health": 61.3, "signals": []})
    assert not _regime_is_empty({"health": None, "signals": [{"key": "x"}]})


def test_merge_regime_preserves_blanked_regions(tmp_path) -> None:
    prior = {"countries": {
        "psx": {"health": 55.0, "signals": [{"key": "a"}]},
        "us": {"health": 61.3, "signals": [{"key": "b"}]},
        "india": {"health": 41.9, "signals": [{"key": "c"}]},
    }}
    path = _write(tmp_path, "macro_regime.json", prior)
    # A PSX-only run: only psx populated, others blank.
    fresh = {"countries": {
        "psx": {"health": 60.0, "signals": [{"key": "a2"}]},
        "us": {"health": None, "signals": []},
        "india": {"health": None, "signals": []},
    }}
    out = _merge_regime(fresh, path)
    assert out["countries"]["psx"]["health"] == 60.0        # fresh wins
    assert out["countries"]["us"]["health"] == 61.3         # preserved
    assert out["countries"]["india"]["health"] == 41.9      # preserved


def test_merge_regime_no_file_returns_fresh(tmp_path) -> None:
    fresh = {"countries": {"psx": {"health": 60.0, "signals": []}}}
    assert _merge_regime(fresh, tmp_path / "missing.json") == fresh


def test_merge_sector_stats_preserves_regions(tmp_path) -> None:
    prior = {"psx": [{"sector": "Cement"}], "us": [{"sector": "Tech"}]}
    path = _write(tmp_path, "sector_stats.json", prior)
    fresh = {"psx": [{"sector": "Cement2"}]}  # us missing this run
    out = _merge_sector_stats(fresh, path)
    assert out["psx"] == [{"sector": "Cement2"}]  # fresh wins
    assert out["us"] == [{"sector": "Tech"}]      # preserved
