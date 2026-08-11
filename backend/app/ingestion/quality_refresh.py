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

_MULTIPLES: dict = {}


def refresh_quality(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    with snapshot_lock("refresh-quality", data_dir) as ok:
        if not ok:
            return {"skipped": 1}
        return _refresh_quality(data_dir, limit)


# A peer group needs enough members for its median to mean anything. Below this we fall back
# to the sector, and failing that to the absolute anchors - a median of three companies is not
# an industry norm, it is an accident.
MIN_PEER_GROUP = 5


def _peer_margins(rows: list[dict], cdir: Path) -> dict[str, dict[str, float]]:
    """Median gross / operating / net margin per industry, and per sector as a fallback.

    Margins only rank companies once they are compared with comparable businesses: an absolute
    threshold ranks industries instead, putting every software company above every retailer
    regardless of which is the better operator.
    """
    buckets: dict[str, dict[str, list[float]]] = {}

    for r in rows:
        cf = safe_file(cdir, f"{r.get('provider_symbol')}.json")
        if cf is None or not cf.exists():
            continue
        try:
            doc = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        inc = ((doc.get("statements") or {}).get("income") or [{}])[0]
        revenue = inc.get("revenue")
        if not revenue or revenue <= 0:
            continue

        for key, group in (("industry", r.get("industry")), ("sector", r.get("sector"))):
            if not group:
                continue
            bucket = buckets.setdefault(f"{key}:{group}", {})
            for metric, field in (("gross_margin", "gross_profit"),
                                  ("operating_margin", "operating_income"),
                                  ("net_margin", "net_income")):
                value = inc.get(field)
                if value is not None:
                    bucket.setdefault(metric, []).append(value / revenue)

    medians: dict[str, dict[str, float]] = {}
    for group, metrics in buckets.items():
        out = {}
        for metric, values in metrics.items():
            if len(values) >= MIN_PEER_GROUP:
                values.sort()
                out[metric] = values[len(values) // 2]
        if out:
            medians[group] = out
    log.info("peer margins: %d groups with a usable median", len(medians))
    return medians


def _peers_for(row: dict, medians: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Industry median where the group is big enough, otherwise the sector's."""
    for key, group in (("industry", row.get("industry")), ("sector", row.get("sector"))):
        if group and f"{key}:{group}" in medians:
            return medians[f"{key}:{group}"]
    return None


def _refresh_quality(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    out = Path(data_dir)
    cdir = out / "company"
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))

    targets = [r for r in rows if r.get("provider_symbol")]
    if limit is not None:
        targets = targets[:limit]

    medians = _peer_margins(targets, cdir)
    # Sector multiples once for the whole run - each one is a median over the entire market,
    # so computing it per company would be the same scan ten thousand times.
    global _MULTIPLES
    try:
        from app.engines.valuation.multi import sector_multiples
        _MULTIPLES = sector_multiples(rows, cdir)
        log.info("sector multiples: %d sectors", len(_MULTIPLES))
    except Exception as exc:  # noqa: BLE001
        log.warning("sector multiples failed: %s", exc)
        _MULTIPLES = {}

    scored = passed = improving = no_data = 0
    for r in targets:
        cf = safe_file(cdir, f"{r['provider_symbol']}.json")
        if cf is None or not cf.exists():
            continue
        try:
            doc = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # The quarterly TTM series is the better view and the one the per-quarter columns are
        # built from. Reading the annual sampling here instead made the headline score disagree
        # with its own newest quarter by up to 38 points, on the same date - two numbers for the
        # same question, with nothing to say which was right.
        statements = doc.get("statements_ttm") or doc.get("statements") or {}

        # The period we HOLD data for, set whether or not it could be scored. It used to be
        # written only by the history pass, which runs only when a score is produced - so a
        # company we cannot score kept the last period we could, and HWQS advertised results to
        # Mar-26 while its Jun-26 statements sat in the same file. What we hold and what we can
        # measure are different facts and the row should not conflate them.
        _inc = (statements.get("income") or [])
        if _inc:
            _newest = str(_inc[0].get("fiscal_date") or "")[:10]
            if _newest:
                r["results_through"] = _newest
        if not (statements.get("income") or []):
            no_data += 1
            continue

        # Valuation needs a quote. Passing the row's own price keeps the two in step - a score
        # computed against a different company's price would be worse than no score.
        q = assess_quality(statements,
                           sector=r.get("sector"),
                           market={
            "price": r.get("price"),
            "market_cap": r.get("market_cap"),
        }, peers=_peers_for(r, medians))
        r["quality_score"] = q.score
        r["quality_passed"] = q.passed
        r["quality_improving"] = q.improving
        # The six-category engine computes far more than the headline number, and all of it
        # was being discarded. The grade names what the score means, and confidence says how
        # much of it rests on real data - a 62 built on four periods and half the inputs is
        # not the same claim as a 62 built on twenty and all of them.
        r["quality_grade"] = q.grade_label
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

        # DCF fair value. Kept OUT of the fundamental score deliberately: the six categories
        # measure business quality, and what a share is worth depends on its price, which is not
        # a quality. Mixing them would mean a great company got marked down for being expensive
        # inside a number that claims to describe the business.
        try:
            from app.engines.valuation.dcf import value as dcf_value

            dcf = dcf_value(statements, r.get("price"), r.get("region") or "",
                            symbol=r.get("symbol"))
            r["dcf_fair_value"] = dcf.fair_value
            r["dcf_upside_pct"] = dcf.upside_pct
            r["dcf_verdict"] = dcf.verdict
            # Several methods, routed by sector, averaged. The published fair value prefers the
            # BLEND wherever it managed more than one method - one model's answer is a view,
            # two agreeing is evidence - and falls back to the DCF alone otherwise.
            from app.engines.valuation.multi import blend as blend_value

            mv = blend_value(statements, r.get("price"), r.get("region") or "",
                             r.get("sector"), r.get("symbol"), _MULTIPLES,
                             industry=r.get("industry"))
            # Prefer the blend on two methods - or on ONE, where the DCF is not a method this
            # sector should be using at all. Falling back to the DCF for a bank or a property
            # developer reinstates exactly the mismatch the routing exists to remove: Emaar
            # reverted to 50.18 against a price of 11.30 the moment its peer group thinned.
            dcf_is_wrong_tool = mv.bucket in ("financial", "real_estate")
            if mv.fair_value and (mv.used >= 2 or dcf_is_wrong_tool):
                r["dcf_fair_value"] = mv.fair_value
                r["dcf_upside_pct"] = mv.upside_pct
                r["dcf_verdict"] = mv.verdict
            doc["valuation"] = {
                "fair_value": mv.fair_value, "upside_pct": mv.upside_pct,
                "verdict": mv.verdict, "methods": mv.methods, "used": mv.used,
                "spread_pct": mv.spread_pct, "bucket": mv.bucket, "reason": mv.reason,
            }
            r["beta"] = (dcf.assumptions or {}).get("beta")
            # Market cap at last: shares x the live price. It was absent from every
            # row in the platform, which is what forced book-weighted WACC.
            r["market_cap"] = (dcf.assumptions or {}).get("market_cap")
            doc["dcf"] = {
                "fair_value": dcf.fair_value, "upside_pct": dcf.upside_pct,
                "verdict": dcf.verdict, "wacc": dcf.wacc,
                "cost_of_equity": dcf.cost_of_equity, "growth": dcf.growth,
                "terminal_growth": dcf.terminal_growth, "base_fcf": dcf.base_fcf,
                "quarters_used": dcf.quarters_used, "net_debt": dcf.net_debt,
                "equity_value": dcf.equity_value, "shares": dcf.shares,
                "assumptions": dcf.assumptions, "reason": dcf.reason,
            }
        except Exception as exc:  # noqa: BLE001 - a valuation must not fail the scoring pass
            log.debug("dcf failed for %s: %s", r.get("symbol"), exc)

        # The full scorecard, for the company page: category-by-category, the current TTM
        # figures behind it, and any earnings-quality red flags.
        doc["fundamental_scorecard"] = {
            "score": q.score, "grade": q.grade_label,
            "categories": q.categories, "metrics": q.metrics, "flags": q.flags,
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
