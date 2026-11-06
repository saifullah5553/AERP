"""The local job publishes five rows. It must not be able to harm the other eleven thousand."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


job = load("psx_local_reads")


def row(symbol: str, as_of: str | None, score: float | None = 50.0) -> dict:
    return {"provider_symbol": symbol, "technical_as_of": as_of, "technical_score": score}


def test_a_read_that_moved_forward_is_published() -> None:
    before = {"HUBC.KA": row("HUBC.KA", "2026-11-04")}
    after = {"HUBC.KA": row("HUBC.KA", "2026-11-05")}

    assert job.newer_reads(before, after) == after


def test_a_withdrawn_read_is_never_published() -> None:
    """Past seven days without a chart the pass blanks the row. The tip's read must stand."""
    before = {"HUBC.KA": row("HUBC.KA", "2026-11-04")}
    after = {"HUBC.KA": row("HUBC.KA", "2026-11-12", score=None)}

    assert job.newer_reads(before, after) == {}


def test_the_same_session_again_publishes_nothing() -> None:
    before = {"HUBC.KA": row("HUBC.KA", "2026-11-05")}

    assert job.newer_reads(before, {"HUBC.KA": row("HUBC.KA", "2026-11-05", 60.0)}) == {}


def test_the_fundamental_side_stays_as_published() -> None:
    """The technical pass leaves quality_score blank, which took HUBC from a buy to a hold."""
    published = {"quality_score": 78.6, "quality_grade": "VERY STRONG", "fundamental_score": 78.6,
                 "quality_passed": False, "strategy_action": "avoid", "technical_score": 53.3}
    passed = {"quality_score": None, "quality_grade": None, "fundamental_score": None,
              "quality_passed": True, "strategy_action": "watch", "technical_score": 55.0}

    kept = job.keep_fundamentals(published, passed)

    assert kept["technical_score"] == 55.0
    assert {k: kept[k] for k in published if k != "technical_score"} == {
        k: published[k] for k in published if k != "technical_score"}


def test_only_our_rows_change_and_nothing_is_lost() -> None:
    rows = [row("AAPL", "2026-11-05"), row("HUBC.KA", "2026-11-04"), {"symbol": "no provider"}]
    fresh = row("HUBC.KA", "2026-11-05")

    assert job.splice(rows, {"HUBC.KA": fresh}) == [rows[0], fresh, rows[2]]


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "checkout", "-q", "-b", "main")
    (work / "a.txt").write_text("one\n", encoding="utf-8")
    git(work, "add", "a.txt")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "origin", "main")
    git(work, "config", "user.name", "t")
    git(work, "config", "user.email", "t@example.invalid")
    monkeypatch.setattr(job.tip_files, "REPO", work)
    return work


def test_a_file_is_rebuilt_from_the_tip_each_attempt_is_built_on(repo: Path) -> None:
    first = git(repo, "rev-parse", "HEAD")
    message = repo.parent / "message.txt"
    message.write_text("change\n", encoding="utf-8")
    seen = []

    def prepare(tip: str) -> None:
        seen.append(tip)
        (repo / "a.txt").write_text("built on the tip\n", encoding="utf-8")

    assert job.tip_files.push(str(message), ["a.txt"], prepare=prepare) == 0

    git(repo, "fetch", "-q", "origin", "main")
    assert seen == [first]
    assert git(repo, "show", "FETCH_HEAD:a.txt") == "built on the tip"
