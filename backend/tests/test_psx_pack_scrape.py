"""The PSX job scrapes for over an hour. Its CSVs go onto the archive as the tip holds it by then."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
PACK = (SCRIPTS / "psx_pack_scrape.sh").as_posix()
PUBLISH = (SCRIPTS / "publish_on_tip.sh").as_posix()
ARCHIVE = "data/psx_csv.tar.gz"
IDENTITY = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def run(*args: str, cwd: Path) -> bytes:
    return subprocess.run(args, cwd=cwd, capture_output=True, check=True,
                          env={**os.environ, **IDENTITY}).stdout


def script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **IDENTITY})


def archive_of(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"psx_csv/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def read_archive(blob: bytes) -> dict[str, str]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return {Path(m.name).name: tar.extractfile(m).read().decode()
                for m in tar.getmembers() if m.isfile()}


def push_archive(repo: Path, files: dict[str, str]) -> None:
    (repo / "data").mkdir(exist_ok=True)
    (repo / ARCHIVE).write_bytes(archive_of(files))
    run("git", "add", ARCHIVE, cwd=repo)
    run("git", "commit", "-qm", "archive", cwd=repo)
    run("git", "push", "-q", "origin", "HEAD:main", cwd=repo)


def scrape(repo: Path, files: dict[str, str]) -> str:
    """Into an ignored folder, as the job does, so that the reset leaves it alone."""
    (repo / ".git" / "info" / "exclude").write_text("scraped/\n", encoding="utf-8")
    folder = repo / "scraped"
    folder.mkdir()
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    return "scraped"


def tip_archive(remote: Path) -> dict[str, str]:
    return read_archive(run("git", "show", f"main:{ARCHIVE}", cwd=remote))


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    bare.mkdir()
    run("git", "init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    seed = tmp_path / "seed"
    run("git", "clone", "-q", str(bare), str(seed), cwd=tmp_path)
    run("git", "checkout", "-q", "-b", "main", cwd=seed)
    push_archive(seed, {"LUCK_Income_Statement.csv": "old\n", "FFC_Income_Statement.csv": "old\n"})
    return bare


def clone(remote: Path, to: Path) -> Path:
    run("git", "clone", "-q", str(remote), str(to), cwd=remote.parent)
    return to


def publish(job: Path, folder: str) -> subprocess.CompletedProcess:
    return script(PUBLISH, "data: test", f'bash "{PACK}" {folder}', ARCHIVE, cwd=job)


def test_the_scrape_lands_on_what_the_tip_holds_by_then(remote: Path, tmp_path: Path) -> None:
    """The replay would have put back the archive this job started from, without HUBC."""
    job = clone(remote, tmp_path / "job")
    folder = scrape(job, {"LUCK_Income_Statement.csv": "sep-26\n"})
    push_archive(clone(remote, tmp_path / "other"), {
        "LUCK_Income_Statement.csv": "old\n", "FFC_Income_Statement.csv": "old\n",
        "HUBC_Income_Statement.csv": "landed during the run\n",
    })

    done = publish(job, folder)

    assert done.returncode == 0, done.stderr
    assert tip_archive(remote) == {
        "LUCK_Income_Statement.csv": "sep-26\n", "FFC_Income_Statement.csv": "old\n",
        "HUBC_Income_Statement.csv": "landed during the run\n",
    }


def test_the_same_scrape_packs_to_the_same_bytes(remote: Path, tmp_path: Path) -> None:
    job = clone(remote, tmp_path / "job")
    folder = scrape(job, {"LUCK_Income_Statement.csv": "sep-26\n"})

    assert publish(job, folder).returncode == 0
    before = run("git", "rev-parse", "main", cwd=remote)
    done = publish(job, folder)

    assert done.returncode == 0, done.stderr
    assert "Nothing changed" in done.stdout
    assert run("git", "rev-parse", "main", cwd=remote) == before


def test_a_run_that_scraped_nothing_leaves_the_archive_alone(remote: Path, tmp_path: Path) -> None:
    job = clone(remote, tmp_path / "job")
    before = (job / ARCHIVE).read_bytes()

    done = script(PACK, "not-there", cwd=job)

    assert done.returncode == 0, done.stderr
    assert (job / ARCHIVE).read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_a_bad_archive_is_not_replaced_by_the_scrape(remote: Path, tmp_path: Path,
                                                     damage: str) -> None:
    """Otherwise a few dozen scraped CSVs would become the whole archive."""
    job = clone(remote, tmp_path / "job")
    folder = scrape(job, {"LUCK_Income_Statement.csv": "sep-26\n"})
    if damage == "missing":
        (job / ARCHIVE).unlink()
    else:
        (job / ARCHIVE).write_bytes(b"not a tar file")
    before = (job / ARCHIVE).read_bytes() if damage == "corrupt" else None

    done = script(PACK, folder, cwd=job)

    assert done.returncode != 0
    assert ((job / ARCHIVE).read_bytes() if damage == "corrupt" else None) == before
