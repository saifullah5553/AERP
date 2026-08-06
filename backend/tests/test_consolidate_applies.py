"""Consolidating must also reach the company files.

Scoring reads `statements_ttm` out of frontend/public/data/company/<sym>.json - never out of
the store. So a consolidate that updates only the store moves nothing any page can see, and
says so in neither its logs nor its exit code.

That is not hypothetical. After the US scrape finished on 2026-08-06 the store held 5,084
companies with up to twenty quarters each, and 116 of them scored blank on the dashboard: the
store was current, the company files were not, and every command involved reported success.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from app.cli import cmd_consolidate_fundamentals


def _args(**kw) -> argparse.Namespace:
    base = {"csv_dir": "", "store_dir": "", "regions": None,
            "data_dir": None, "no_apply": False}
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture()
def spy(monkeypatch):
    """Record what the command calls, without touching a real snapshot."""
    calls: dict[str, object] = {}
    import app.ingestion.fundamentals_store as store

    def fake_consolidate(*args, **kwargs):
        calls["consolidate"] = args
        return {}

    def fake_apply(*args, **kwargs):
        calls["apply"] = args
        return {}

    monkeypatch.setattr(store, "consolidate", fake_consolidate)
    monkeypatch.setattr(store, "apply_to_snapshot", fake_apply)
    return calls


def test_consolidating_also_applies_to_the_company_files(spy, tmp_path) -> None:
    """The whole point: one command leaves the store and the company files agreeing."""
    cmd_consolidate_fundamentals(_args(csv_dir=str(tmp_path), store_dir=str(tmp_path),
                                       data_dir=str(tmp_path)))
    assert "consolidate" in spy
    assert "apply" in spy, "the store moved but the company files did not - the 2026-08-06 bug"


def test_no_apply_is_available_but_must_be_asked_for(spy, tmp_path) -> None:
    """An escape hatch for the rare case, never the default."""
    cmd_consolidate_fundamentals(_args(csv_dir=str(tmp_path), store_dir=str(tmp_path),
                                       data_dir=str(tmp_path), no_apply=True))
    assert "consolidate" in spy
    assert "apply" not in spy


def test_the_regions_reach_the_apply_step(spy, tmp_path) -> None:
    """Consolidating one market must not re-apply every other market's store."""
    cmd_consolidate_fundamentals(_args(csv_dir=str(tmp_path), store_dir=str(tmp_path),
                                       data_dir=str(tmp_path), regions="psx"))
    assert spy["apply"][2] == ["psx"]


def test_the_parser_accepts_the_new_flags() -> None:
    """A flag the parser rejects is a command that dies at the shell, not a safer default."""
    from app.cli import build_parser

    ns = build_parser().parse_args(
        ["consolidate-fundamentals", "--regions", "us", "--no-apply"])
    assert ns.no_apply is True and ns.regions == "us"
    ns = build_parser().parse_args(["consolidate-fundamentals"])
    assert ns.no_apply is False, "applying must be what happens when nobody says otherwise"


def test_a_blank_company_file_is_what_the_bug_looked_like(tmp_path) -> None:
    """Documents the symptom, so a future reader recognises it rather than re-diagnosing it.

    A company file with no `statements_ttm` scores blank no matter how complete the store is.
    """
    doc = json.loads('{"symbol": "GAIA", "statements": {"income": []}}')
    assert not (doc.get("statements_ttm") or {}).get("income")
    Path(tmp_path / "GAIA.json").write_text(json.dumps(doc), encoding="utf-8")
