"""Re-sort the screener and regenerate derived snapshot files after a data change.

Keeps market breadth (pulse.json) and the securities count (meta.json) in step with whatever
scores were just written, so the dashboard never shows stale aggregates. Run from backend/:
    python ../scripts/consolidate_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")  # run from backend/
from app.services.pulse import pulse_from_screener_dicts  # noqa: E402

OUT = Path("../frontend/public/data")


def main() -> int:
    rows = json.loads((OUT / "screener.json").read_text(encoding="utf-8"))
    rows.sort(
        key=lambda r: (r.get("composite_score") is not None, r.get("composite_score") or 0),
        reverse=True,
    )
    (OUT / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    (OUT / "pulse.json").write_text(json.dumps(pulse_from_screener_dicts(rows)), encoding="utf-8")

    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    meta["securities"] = len(rows)
    (OUT / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    covered = sum(1 for r in rows if r.get("fundamental_score") is not None)
    print(f"consolidated {len(rows)} rows | fundamentals: {covered}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
