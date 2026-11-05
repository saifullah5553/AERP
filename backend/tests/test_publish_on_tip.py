"""A job that runs for hours must not put back what other jobs published while it ran."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "publish_on_tip.sh"
IDENTITY = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def run(*args: str, cwd: Path) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, **IDENTITY})
    return done.stdout


def clone(remote: Path, to: Path) -> Path:
    run("git", "clone", "-q", str(remote), str(to), cwd=remote.parent)
    return to


def write_and_push(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8", newline="\n")
    run("git", "add", name, cwd=repo)
    run("git", "commit", "-qm", f"write {name}", cwd=repo)
    run("git", "push", "-q", "origin", "HEAD:main", cwd=repo)


def tip(remote: Path, name: str) -> str:
    return run("git", "show", f"main:{name}", cwd=remote)


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    bare.mkdir()
    run("git", "init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    seed = clone(bare, tmp_path / "seed")
    run("git", "checkout", "-q", "-b", "main", cwd=seed)
    write_and_push(seed, "store.txt", "base\n")
    return bare


def publish(repo: Path, build: str, *paths: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", SCRIPT.as_posix(), "data: test", build, *paths], cwd=repo,
                          capture_output=True, text=True, env={**os.environ, **IDENTITY})


def test_what_landed_during_the_run_survives_it(remote: Path, tmp_path: Path) -> None:
    """India's September results, pushed while the Fundamentals job was scraping."""
    job = clone(remote, tmp_path / "job")
    write_and_push(clone(remote, tmp_path / "other"), "store.txt", "base\nindia\n")

    done = publish(job, "echo us >> store.txt", "store.txt")

    assert done.returncode == 0, done.stderr
    assert tip(remote, "store.txt") == "base\nindia\nus\n"


def test_a_push_during_the_build_starts_the_build_again(remote: Path, tmp_path: Path) -> None:
    job = clone(remote, tmp_path / "job")
    rival = clone(remote, tmp_path / "rival")
    # An ignored-style marker outside the repo, so that the reset leaves it alone.
    once = tmp_path / "pushed-once"
    rival_push = (f'if [ ! -e "{once.as_posix()}" ]; then touch "{once.as_posix()}"; '
                  f'cd "{rival.as_posix()}" && echo india >> store.txt && git add store.txt '
                  '&& git commit -qm rival && git push -q origin HEAD:main; fi')

    done = publish(job, f"({rival_push}); echo us >> store.txt", "store.txt")

    assert done.returncode == 0, done.stderr
    assert "Starting again" in done.stdout
    assert tip(remote, "store.txt") == "base\nindia\nus\n"


def test_files_fetched_outside_the_repo_survive_the_reset(remote: Path, tmp_path: Path) -> None:
    """The scraped CSVs are ignored paths, and they are the whole point of the run."""
    job = clone(remote, tmp_path / "job")
    (job / ".git" / "info" / "exclude").write_text("scraped.csv\n", encoding="utf-8")
    (job / "scraped.csv").write_text("sep-26\n", encoding="utf-8", newline="\n")

    done = publish(job, "cat scraped.csv >> store.txt", "store.txt")

    assert done.returncode == 0, done.stderr
    assert tip(remote, "store.txt") == "base\nsep-26\n"


def test_only_the_named_paths_are_published(remote: Path, tmp_path: Path) -> None:
    job = clone(remote, tmp_path / "job")

    done = publish(job, "echo us >> store.txt; echo noise > stray.txt", "store.txt")

    assert done.returncode == 0, done.stderr
    assert "stray.txt" not in run("git", "ls-tree", "--name-only", "main", cwd=remote)


def test_no_change_publishes_nothing(remote: Path, tmp_path: Path) -> None:
    job = clone(remote, tmp_path / "job")
    before = run("git", "rev-parse", "main", cwd=remote)

    done = publish(job, "true", "store.txt")

    assert done.returncode == 0, done.stderr
    assert run("git", "rev-parse", "main", cwd=remote) == before


def test_a_failed_build_publishes_nothing(remote: Path, tmp_path: Path) -> None:
    job = clone(remote, tmp_path / "job")
    before = run("git", "rev-parse", "main", cwd=remote)

    done = publish(job, "echo half >> store.txt; exit 1", "store.txt")

    assert done.returncode != 0
    assert run("git", "rev-parse", "main", cwd=remote) == before
