from __future__ import annotations

import json
from pathlib import Path

from app.services.raw_materials import build_raw_materials, classify_trend


def test_classify_trend() -> None:
    assert classify_trend(90, 100, 110) == "decreasing"   # below both, stacked down
    assert classify_trend(120, 110, 100) == "increasing"  # above both, stacked up
    assert classify_trend(100, 100, 100) == "sideways"
    assert classify_trend(90, 100, None) == "decreasing"  # fallback to sma50
    assert classify_trend(None, None, None) == "sideways"


def _commodity_file(dir_: Path, sym: str, close: float, s50: float, s200: float) -> None:
    (dir_ / f"{sym}=F.json").write_text(json.dumps({
        "security": {"symbol": sym, "name": sym},
        "quote": {"price": close, "change_pct": 1.0},
        "technical": {"sma_50": s50, "sma_200": s200},
    }), encoding="utf-8")


def test_build_raw_materials(tmp_path: Path) -> None:
    comp = tmp_path / "company"
    comp.mkdir()
    _commodity_file(comp, "NG", 2.0, 2.5, 3.0)   # decreasing
    _commodity_file(comp, "CL", 90.0, 80.0, 70.0)  # increasing

    rm = build_raw_materials(comp)
    assert rm["commodities"]["NG"]["trend"] == "decreasing"
    assert rm["commodities"]["CL"]["trend"] == "increasing"
    # cement maps to NG + CL and both are present
    cement = next(s for s in rm["sector_map"] if "cement" in s["keywords"])
    assert set(cement["materials"]) == {"NG", "CL"}
    assert rm["counts"]["decreasing"] == 1 and rm["counts"]["increasing"] == 1
