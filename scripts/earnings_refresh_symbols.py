"""Print tickers whose earnings date just passed — i.e. companies that just reported results.

Their fundamentals are stale by definition (a new quarter landed), so these are the names worth
re-fetching. Mirrors scripts/psx_result_symbols.py, but for US/India/Australia where the trigger
is `next_earnings_date` (from yfinance estimates) rather than a PSX filing announcement.

Usage:  python scripts/earnings_refresh_symbols.py [lookback_days] [cap]
"""

from __future__ import annotations

import datetime
import glob
import json
import sys

COMPANY_GLOB = "frontend/public/data/company/*.json"
REGIONS = {"us", "india", "australia"}


def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=days)).isoformat()
    today_s = today.isoformat()

    out: list[tuple[str, str]] = []
    for path in glob.glob(COMPANY_GLOB):
        try:
            with open(path, encoding="utf-8") as fh:
                sec = (json.load(fh).get("security") or {})
        except (OSError, json.JSONDecodeError):
            continue
        if sec.get("region") not in REGIONS:
            continue
        ned = str(sec.get("next_earnings_date") or "")[:10]
        sym = sec.get("provider_symbol") or sec.get("symbol")
        # Reported within the lookback window (date has passed but is recent).
        if sym and ned and since <= ned < today_s:
            out.append((ned, str(sym)))

    out.sort(reverse=True)  # most recently reported first
    print(",".join(sym for _d, sym in out[:cap]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
