"""Read and write named files on the remote tip, without touching the working tree or the index.

This checkout usually sits behind main: CI commits a snapshot several times a day, and pulling it
means rewriting ten thousand files. So local jobs must not commit from here. `git add` plus a merge
would publish this machine's stale snapshot over CI's, which is what the old earnings script did.

    tip_files.py pull data/fundamentals_ttm/us.json.gz            copy from the tip
    tip_files.py pull frontend/public/data/screener.json=data/x.json     ... to another path
    tip_files.py push message.txt data/fundamentals_ttm/us.json.gz       commit these onto the tip

A push builds its tree from the tip in a temporary index, adds the named files, and refuses unless
the resulting diff is inside that list. Named files that have not changed are simply skipped.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ATTEMPTS = 3


def git(*args: str, env: dict[str, str] | None = None, text: bool = True):
    done = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=text,
                          env={**os.environ, **(env or {})})
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {done.stderr}")
    return done.stdout.strip() if text else done.stdout


def fetch_tip() -> str:
    git("-c", "gc.auto=0", "fetch", "-q", "origin", "main")
    return git("rev-parse", "FETCH_HEAD")


def outside(changed: list[str], named: list[str]) -> list[str]:
    """Paths a commit would change that nobody asked it to."""
    return sorted(set(changed) - set(named))


def pull(specs: list[str]) -> int:
    tip = fetch_tip()
    for spec in specs:
        source, _, target = spec.partition("=")
        path = REPO / (target or source)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git("cat-file", "-p", f"{tip}:{source}", text=False))
    print(f"pulled {len(specs)} file(s) from {tip[:12]}")
    return 0


def push(message_file: str, named: list[str]) -> int:
    with tempfile.TemporaryDirectory() as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        for _ in range(ATTEMPTS):
            tip = fetch_tip()
            git("read-tree", tip, env=index)
            for name in named:
                blob = git("hash-object", "-w", f"--path={name}", name)
                git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=index)
            tree = git("write-tree", env=index)
            commit = git("commit-tree", tree, "-p", tip, "-F", message_file)
            changed = git("diff", "--name-only", tip, commit).splitlines()
            if not changed:
                print("nothing changed on the tip")
                return 0
            extra = outside(changed, named)
            if extra:
                print(f"REFUSED, would also change: {extra[:10]}")
                return 1
            try:
                git("push", "-q", "origin", f"{commit}:refs/heads/main")
            except RuntimeError:
                continue    # someone pushed in between; rebuild on the new tip
            print(f"pushed {commit[:12]} on {tip[:12]}: {changed}")
            return 0
    print("push rejected on every attempt")
    return 1


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "pull":
        return pull(sys.argv[2:])
    if len(sys.argv) >= 4 and sys.argv[1] == "push":
        return push(sys.argv[2], sys.argv[3:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
