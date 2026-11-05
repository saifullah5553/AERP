"""Local jobs publish named files only, and never this checkout's stale snapshot."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("tip_files", ROOT / "scripts" / "tip_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(path: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.name", "test")
    run("config", "user.email", "test@example.com")


def test_a_path_nobody_named_is_reported() -> None:
    tip = _module()
    assert tip.outside(["a", "b"], ["a"]) == ["b"]
    assert tip.outside(["a"], ["a", "b"]) == []


def test_a_push_leaves_this_machines_stale_file_behind(tmp_path, monkeypatch) -> None:
    """The working tree here is behind: `stale.json` differs from the tip and must stay out."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work.mkdir()
    _repo(work)
    (work / "store.gz").write_text("old", encoding="utf-8")
    (work / "stale.json").write_text("from CI", encoding="utf-8")
    for args in (["add", "-A"], ["commit", "-qm", "base"], ["remote", "add", "origin", str(origin)],
                 ["push", "-q", "origin", "main"]):
        subprocess.run(["git", "-C", str(work), *args], check=True, capture_output=True)

    (work / "store.gz").write_text("new results", encoding="utf-8")
    (work / "stale.json").write_text("this machine's old copy", encoding="utf-8")
    message = tmp_path / "message.txt"
    message.write_text("data: results", encoding="utf-8")

    tip = _module()
    monkeypatch.setattr(tip, "REPO", work)
    assert tip.push(str(message), ["store.gz"]) == 0

    def published(name: str) -> str:
        return subprocess.run(["git", "--git-dir", str(origin), "show", f"main:{name}"],
                              check=True, capture_output=True, text=True).stdout

    assert published("store.gz") == "new results"
    assert published("stale.json") == "from CI"


def test_the_scheduled_script_never_commits_the_snapshot() -> None:
    script = (ROOT / "scripts" / "earnings_refresh_local.ps1").read_text(encoding="utf-8")
    code = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not any("git add" in line or "git pull" in line or "git push" in line for line in code)
