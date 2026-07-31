"""Aggregate recent insider transactions across all markets into a single feed.

Reads the exported company/*.json (which already carry per-company insider transactions
for US / India / Australia / PSX) and flattens the most recent ones into insider.json for
the Alerts "Insider" table. No DB needed, so it covers every market in the snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_insider_feed(company_dir: str | Path, limit: int = 500) -> list[dict]:
    company_dir = Path(company_dir)
    rows: list[dict] = []
    for f in company_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sec = d.get("security") or {}
        for t in d.get("insider") or []:
            date = t.get("transaction_date") or t.get("filed_at")
            if not date:
                continue
            rows.append({
                "symbol": sec.get("symbol"),
                "provider_symbol": sec.get("provider_symbol"),
                "region": sec.get("region"),
                "company": sec.get("name"),
                "insider": t.get("insider_name"),
                "title": t.get("insider_title"),
                "type": str(t.get("transaction_type") or "").lower(),
                "shares": _num(t.get("shares")),
                "value": _num(t.get("value")),
                "date": str(date)[:10],
            })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit]
