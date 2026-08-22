"""The post-condition check must actually fail when something is stale.

A checker that passes on bad data is worse than no checker: it converts "nobody looked" into
"we looked and it was fine". Every test here feeds it data that IS broken and asserts it
says so.
"""

from __future__ import annotations

import datetime
import gzip
import json
from pathlib import Path

from app.ingestion.freshness import verify

TODAY = datetime.date(2026, 8, 22)


def _pack(path: Path, newest: str, symbols: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {f"SYM{i}": {"d": ["2026-01-02", newest], "c": [10.0, 11.0]} for i in range(symbols)}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(data))


def _world(tmp: Path, price_day="2026-08-21", bar_day="2026-08-21",
           scored=True, grade="STRONG", score=70.0):
    data = tmp / "frontend" / "public" / "data"
    (data / "company").mkdir(parents=True)
    rows = []
    for m in ("psx", "us", "india", "australia", "gcc", "dfm"):
        for i in range(10):
            rows.append({
                "provider_symbol": f"{m.upper()}{i}", "region": m, "asset_class": "equity",
                "price_as_of": price_day,
                "quality_score": (score if scored else None),
                "quality_grade": (grade if scored else None),
            })
    (data / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    stamp = "2026-08-22T09:00:00+00:00"
    for name in ("macro_regime.json", "model_portfolio.json", "meta.json"):
        (data / name).write_text(json.dumps({"generated_at": stamp}), encoding="utf-8")
    for m in ("psx", "us", "india", "australia", "gcc", "dfm", "global"):
        _pack(tmp / "data" / "prices" / f"{m}.json.gz", bar_day)
    return data


def test_a_healthy_platform_passes(tmp_path: Path) -> None:
    data = _world(tmp_path)
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed == 0, [c.line() for c in checks if not c.ok]
    assert len(checks) > 15


def test_stale_bars_in_one_market_fail(tmp_path: Path) -> None:
    """The exact defect this was written for: PSX bars stopped on 3 August while prices stayed
    current, so the screener looked right and every PSX technical was computed on a dead chart
    for nineteen days."""
    data = _world(tmp_path)
    _pack(tmp_path / "data" / "prices" / "psx.json.gz", "2026-08-03")
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed == 1
    bad = [c for c in checks if not c.ok][0]
    assert bad.name == "bars[psx]"
    assert "19d" in bad.detail


def test_stale_prices_fail(tmp_path: Path) -> None:
    data = _world(tmp_path, price_day="2026-08-01")
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed >= 6                      # every market is stale
    assert any(c.name == "prices[psx]" and not c.ok for c in checks)


def test_a_market_that_stops_scoring_fails(tmp_path: Path) -> None:
    """Coverage is checked as a RATIO per market. A market that quietly halves has broken even
    though every number still in it looks perfectly reasonable."""
    data = _world(tmp_path)
    rows = json.loads((data / "screener.json").read_text(encoding="utf-8"))
    for r in rows:
        if r["region"] == "india":
            r["quality_score"] = None
            r["quality_grade"] = None
    (data / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed == 1
    assert [c for c in checks if not c.ok][0].name == "scored[india]"


def test_a_grade_contradicting_its_score_fails(tmp_path: Path) -> None:
    """JPMorgan read 61.6 labelled VERY STRONG, and a third of the universe was the same."""
    data = _world(tmp_path, score=61.6, grade="VERY STRONG")
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed == 1
    assert [c for c in checks if not c.ok][0].name == "grade matches score"


def test_a_missing_pack_fails_rather_than_being_skipped(tmp_path: Path) -> None:
    """An absent artifact must not read as a passing one - that is the whole failure mode."""
    data = _world(tmp_path)
    (tmp_path / "data" / "prices" / "gcc.json.gz").unlink()
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed == 1
    bad = [c for c in checks if not c.ok][0]
    assert bad.name == "bars[gcc]" and "missing" in bad.detail


def test_a_stale_snapshot_file_fails(tmp_path: Path) -> None:
    data = _world(tmp_path)
    (data / "macro_regime.json").write_text(
        json.dumps({"generated_at": "2026-08-10T09:00:00+00:00"}), encoding="utf-8")
    checks, failed = verify(data, repo_root=tmp_path, today=TODAY)
    assert failed == 1
    assert [c for c in checks if not c.ok][0].name == "file[macro_regime.json]"


def test_the_pack_round_trips_volume(tmp_path: Path, monkeypatch) -> None:
    """Volume must survive write -> read, or EFI divergences silently degrade to RSI-only.

    `packed_bars` always had a volume column and always returned None in it. PSX ran that way
    for months: the divergence page showed RSI signals and no EFI ones, which looks exactly
    like a market that happens to have no force divergences.
    """
    from app.ingestion import price_pack

    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path)
    price_pack._CACHE.clear()
    price_pack._VOL_CACHE.clear()

    price_pack.merge_series(
        "psx",
        {"LUCK": {"2026-08-21": 440.41, "2026-08-22": 442.0}},
        volumes={"LUCK": {"2026-08-21": 581614.0, "2026-08-22": 601000.0}},
    )
    bars = price_pack.packed_bars("psx", "LUCK")
    assert bars["2026-08-21"][4] == 440.41          # close
    assert bars["2026-08-21"][5] == 581614.0        # volume, no longer None
    assert bars["2026-08-22"][5] == 601000.0

    # A later close-only merge must not wipe the volume already stored.
    price_pack.merge_series("psx", {"LUCK": {"2026-08-25": 445.0}})
    bars = price_pack.packed_bars("psx", "LUCK")
    assert bars["2026-08-21"][5] == 581614.0
    assert bars["2026-08-25"][5] is None            # no volume for that day, not a zero
