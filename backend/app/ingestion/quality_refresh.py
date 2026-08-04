"""Compute the fundamental quality score for EVERY stock, from stored statements only.

Quality needs no prices — it reads revenue/profit/EPS/cash/debt out of the statements we
already hold. Bundling it into tech_refresh meant it was gated behind an OHLC fetch per name
and a --limit, so most of the universe never got a score. This runs it standalone: pure local
work, no network, whole universe in one pass.

Writes quality_score / quality_passed / quality_improving onto the screener rows and the
company files. The entry-timing half of the strategy (which does need prices) is still filled
by tech_refresh; a name scored here shows AVOID immediately if it fails the gate, and waits for
tech_refresh to decide BUY vs HOLD vs WATCH if it passes.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.core.snapshot_lock import snapshot_lock
from app.engines.strategy.quality import assess_quality

log = get_logger(__name__)


def refresh_quality(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    with snapshot_lock("refresh-quality", data_dir) as ok:
        if not ok:
            return {"skipped": 1}
        return _refresh_quality(data_dir, limit)


def _refresh_quality(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    out = Path(data_dir)
    cdir = out / "company"
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))

    targets = [r for r in rows if r.get("provider_symbol")]
    if limit is not None:
        targets = targets[:limit]

    scored = passed = improving = no_data = 0
    for r in targets:
        cf = safe_file(cdir, f"{r['provider_symbol']}.json")
        if cf is None or not cf.exists():
            continue
        try:
            doc = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        statements = doc.get("statements") or {}
        if not (statements.get("income") or []):
            no_data += 1
            continue

        # Valuation needs a quote. Passing the row's own price keeps the two in step - a score
        # computed against a different company's price would be worse than no score.
        q = assess_quality(statements, market={
            "price": r.get("price"),
            "market_cap": r.get("market_cap"),
        })
        r["quality_score"] = q.score
        r["quality_passed"] = q.passed
        r["quality_improving"] = q.improving
        # A failed gate is a verdict on its own - no price data needed to say "avoid".
        if not q.eligible:
            r["strategy_action"] = "avoid"
        elif not r.get("strategy_action") or r.get("strategy_action") == "avoid":
            # Passes the gate; tech_refresh decides buy/hold/watch once it has the chart.
            r["strategy_action"] = "watch"

        if isinstance(doc.get("scores"), dict) and q.score is not None:
            doc["scores"]["quality"] = q.score
        strat = doc.get("strategy")
        if isinstance(strat, dict):
            strat.update({
                "quality_passed": q.passed, "quality_improving": q.improving,
                "quality_score": q.score, "quality_checks": q.checks,
                "quality_metrics": q.metrics,
            })
        else:
            doc["strategy"] = {
                "action": r["strategy_action"], "conviction": None,
                "quality_passed": q.passed, "quality_improving": q.improving,
                "quality_score": q.score, "quality_checks": q.checks,
                "quality_metrics": q.metrics, "entry_triggered": None,
                "entry_score": None, "entry_triggers": [], "entry_vetoes": [],
                "rationale": [f"fails quality: {', '.join(q.reasons)}"] if not q.eligible
                else ["passes the quality gate - awaiting price-action timing"],
            }
        try:
            cf.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        except OSError:
            continue

        scored += 1
        passed += 1 if q.passed else 0
        improving += 1 if q.improving else 0

    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    result = {"targets": len(targets), "scored": scored, "passed": passed,
              "improving": improving, "no_statements": no_data}
    log.info("refresh-quality: %s", result)
    return result
