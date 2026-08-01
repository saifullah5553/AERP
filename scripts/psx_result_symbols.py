"""Print PSX symbols that announced results recently (comma-separated, capped).

Used by .github/workflows/psx-fundamentals.yml to decide which companies' stockanalysis
CSVs to re-scrape. Mirrors the frontend's resultsFiled() filter.

Usage:  python scripts/psx_result_symbols.py [days] [cap]
"""

from __future__ import annotations

import datetime
import json
import re
import sys

RESULT_RE = re.compile(
    r"result|financial|accounts|profit|earnings|\beps\b|board meeting|payout", re.I
)
CATALYSTS = "frontend/public/data/catalysts.json"


def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    try:
        with open(CATALYSTS, encoding="utf-8") as fh:
            cat = json.load(fh)
    except (OSError, json.JSONDecodeError):
        cat = {"by_symbol": {}}

    syms: set[str] = set()
    for sym, evs in (cat.get("by_symbol") or {}).items():
        for e in evs:
            if RESULT_RE.search(e.get("title") or "") and (e.get("date") or "") >= since:
                syms.add(sym)
                break

    print(",".join(sorted(syms)[:cap]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
