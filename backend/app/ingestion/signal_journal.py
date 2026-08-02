"""Daily signal journal — an auditable, forward-looking track record.

Every backtest so far has been retrospective, which always invites the question "was this
tuned with hindsight?". This answers it differently: each day we write down what the engine
said and the price it said it at, BEFORE the outcome is known. Nothing here can be revised
after the fact - a date is written once and then left alone.

    record_signals()  - append today's BUY/HOLD calls with the price at the time
    evaluate_journal() - score every past entry against the current price, grouped by month

After a few months this is a real live record, not a simulation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

JOURNAL = "signal_journal.json"
TRACKED = {"buy", "hold"}


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": [], "created_at": datetime.now(UTC).isoformat()}


def record_signals(data_dir: str | Path, today: str | None = None) -> dict[str, int]:
    """Append today's actionable calls. Idempotent: re-running on the same date is a no-op,
    so a repeated CI run can never double-count or overwrite the original price."""
    out = Path(data_dir)
    day = today or datetime.now(UTC).date().isoformat()
    path = out / JOURNAL
    doc = _load(path)
    entries: list[dict] = doc.get("entries", [])

    if any(e.get("date") == day for e in entries):
        log.info("signal-journal: %s already recorded", day)
        return {"recorded": 0, "total": len(entries), "skipped_existing": 1}

    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    added = 0
    for r in rows:
        action = r.get("strategy_action")
        if action not in TRACKED:
            continue
        price = r.get("price")
        if price is None:
            continue
        entries.append({
            "date": day,
            "provider_symbol": r.get("provider_symbol"),
            "symbol": r.get("symbol"),
            "region": r.get("region"),
            "action": action,
            "price": price,
            "quality_score": r.get("quality_score"),
            "conviction": r.get("strategy_conviction"),
        })
        added += 1

    doc["entries"] = entries
    doc["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(doc), encoding="utf-8")
    log.info("signal-journal: recorded %d for %s (total %d)", added, day, len(entries))
    return {"recorded": added, "total": len(entries)}


def evaluate_journal(data_dir: str | Path) -> dict[str, Any]:
    """Score every journalled call against today's price, grouped by the month it was made."""
    out = Path(data_dir)
    doc = _load(out / JOURNAL)
    entries: list[dict] = doc.get("entries", [])
    if not entries:
        return {"entries": 0, "note": "no signals journalled yet"}

    prices = {
        r.get("provider_symbol"): r.get("price")
        for r in json.loads((out / "screener.json").read_text(encoding="utf-8"))
    }

    by_month: dict[str, dict[str, Any]] = {}
    for e in entries:
        now = prices.get(e.get("provider_symbol"))
        entry_px = e.get("price")
        if now is None or not entry_px:
            continue
        ret = (float(now) - float(entry_px)) / float(entry_px) * 100.0
        month = str(e.get("date", ""))[:7]
        b = by_month.setdefault(
            month, {"n": 0, "wins": 0, "rets": [], "action": {}}
        )
        b["n"] += 1
        b["rets"].append(ret)
        if ret > 0:
            b["wins"] += 1
        b["action"][e.get("action")] = b["action"].get(e.get("action"), 0) + 1

    months = {}
    for m, b in sorted(by_month.items()):
        rets = sorted(b["rets"])
        months[m] = {
            "signals": b["n"],
            "win_rate_pct": round(100.0 * b["wins"] / b["n"], 1) if b["n"] else None,
            "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else None,
            "median_return_pct": round(rets[len(rets) // 2], 2) if rets else None,
            "best_pct": round(max(rets), 2) if rets else None,
            "worst_pct": round(min(rets), 2) if rets else None,
            "by_action": b["action"],
        }

    result = {
        "entries": len(entries),
        "first_recorded": min(e.get("date", "") for e in entries),
        "months": months,
        "note": (
            "Returns are measured from the price recorded on the signal date to the current "
            "price - a live, forward-looking record, not a backtest. Positions are still open, "
            "so early months are marked-to-market rather than realised."
        ),
    }
    (out / "signal_performance.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("signal-journal evaluate: %d entries across %d months", len(entries), len(months))
    return result
