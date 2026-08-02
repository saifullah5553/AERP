"""Phased yfinance fundamentals backfill: fetch ~1k names, consolidate, commit + deploy, repeat.

Run from the backend/ dir:  python ../scripts/phased_fundamentals.py
Each phase patches up to 1000 more tail names (real TTM fundamentals), regenerates pulse/meta,
and pushes (which triggers the Pages deploy) — so coverage ships incrementally. Resumable and
cache-backed; stops when no scoreable names remain.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")  # run from backend/
from app.ingestion.fundamentals_web import refresh_fundamentals_web  # noqa: E402
from app.services.pulse import pulse_from_screener_dicts  # noqa: E402

OUT = Path("../frontend/public/data")
PHASE_SIZE = 1000


def _consolidate() -> int:
    rows = json.loads((OUT / "screener.json").read_text(encoding="utf-8"))
    (OUT / "pulse.json").write_text(json.dumps(pulse_from_screener_dicts(rows)), encoding="utf-8")
    m = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    m["securities"] = len(rows)
    (OUT / "meta.json").write_text(json.dumps(m), encoding="utf-8")
    return len(rows)


def _git(*args: str) -> None:
    subprocess.run(["git", "-C", "..", *args], check=False, capture_output=True, text=True)


def _deploy(phase: int, updated: int) -> None:
    _git("add", "frontend/public/data")
    _git("commit", "-q", "-m", f"data: phased fundamentals backfill — phase {phase} (+{updated})")
    _git("pull", "--no-rebase", "-X", "ours", "--no-edit", "origin", "main")
    _git("push", "origin", "main")


def main() -> int:
    phase = 0
    while True:
        phase += 1
        res = refresh_fundamentals_web(str(OUT), region="all", limit=PHASE_SIZE)
        _consolidate()
        _deploy(phase, res["updated"])
        print(f"PHASE {phase}: {res}", flush=True)
        if res["remaining"] == 0 or res["targets"] == 0:
            break
    print("PHASED BACKFILL COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
