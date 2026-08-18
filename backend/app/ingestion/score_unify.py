"""One fundamental score, and it is the same number on every page.

THE PROBLEM THIS ENDS. Atlas Honda showed a fundamental score of 86 on its company page, 73 on
the quality tile beside it, and 69.5 in the model portfolio - three numbers for one question,
on one screen, on the same day. They were not stale copies of each other. They came from
different engines:

    scores.fundamental   85.5   the RETIRED engine (engines/fundamental/scoring.py), written
                                once by the database export and never revisited
    scores.quality       73.23  a composite DIMENSION (engines/composite/dimensions.py) that
                                carries 0.0 weight and exists only as a tile
    quality_score        69.5   the six-category engine the user specified, which is the score
                                the screener, the ledger and the portfolio all rank on

Whichever pass ran last decided what a given page showed, and a company the quality pass
skipped kept the retired engine's number forever - which is exactly what happened to ATLH.

THE RULE. `quality_score` - `engines/strategy/fundamental_quality.py`, six categories out of
100, built only from our own quarterly-TTM CSVs - IS the fundamental score. Everything that
displays one reads the same field, and this pass is where they are made to agree.

WHERE THERE IS NO SCORE, THE OLD ONE IS CLEARED, not left standing. A retired engine's 85.5 in
the space where the current engine has no answer is worse than a blank: it reads as a measured
result. If we cannot score a company today, the page must say so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.engines.fundamental.adaptive import rating_for

log = get_logger(__name__)

# Every field any page has ever read for "the fundamental score". They are written together so
# no page can pick up a different one.
_MIRRORS = ("fundamental_score",)


def _canonical(row: dict) -> float | None:
    """The six-category score for this row, or None when it could not be scored."""
    value = row.get("quality_score")
    return float(value) if isinstance(value, int | float) else None


def _recompute_composite(doc_scores: dict, fund: float | None, region_regime: Any) -> float | None:
    """Reblend using the SAME function the technical pass uses.

    Imported rather than reimplemented: a second copy of the weighting is how the composite
    would start disagreeing with itself the first time either changed. The regime modifier is
    deliberately not applied here - the technical pass owns that and re-applies it on its next
    run, and guessing at it would produce a third number.
    """
    from app.ingestion.tech_refresh import _reblend

    def _f(v: Any) -> float | None:
        return float(v) if isinstance(v, int | float) else None

    base, _coverage, _present = _reblend(
        fund, _f(doc_scores.get("technical")), _f(doc_scores.get("momentum")),
        fund, _f(doc_scores.get("risk")),
    )
    return base


def unify(data_dir: str | Path) -> dict[str, int]:
    """Make every stored fundamental score equal the six-category score. Returns counts."""
    out = Path(data_dir)
    screener = out / "screener.json"
    try:
        rows: list[dict] = json.loads(screener.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("score-unify: no screener to reconcile")
        return {"rows": 0, "aligned": 0, "cleared": 0}

    cdir = out / "company"
    aligned = cleared = files = 0
    for row in rows:
        canonical = _canonical(row)

        if canonical is None:
            # No current score. Drop the retired engine's number rather than let it stand in.
            if any(row.get(k) is not None for k in _MIRRORS):
                cleared += 1
            for key in _MIRRORS:
                row[key] = None
            row["quality_grade"] = None
        else:
            if any(row.get(k) != canonical for k in _MIRRORS):
                aligned += 1
            for key in _MIRRORS:
                row[key] = canonical
            # THE LABEL IS DERIVED FROM THE SCORE, HERE, EVERY TIME.
            #
            # It used to be written by whichever refresh-quality run last touched the row, and
            # a later rescore moved the score without moving the label: 3,143 rows of 9,602 -
            # a third of the universe - ended up carrying a grade from a band their own score
            # no longer sat in. JPMorgan read 61.6 labelled VERY STRONG, which is the 75-84.9
            # band. A trader reading the label got a different answer from one reading the
            # number, on the same row of the same screen.
            #
            # Deriving it at the single point that owns the score is the only arrangement
            # where the two cannot drift apart, for exactly the reason this whole module
            # exists.
            row["quality_grade"] = rating_for(canonical)

        sym = row.get("provider_symbol")
        if not sym:
            continue
        cf = safe_file(cdir, f"{sym}.json")
        if cf is None or not cf.exists():
            continue
        try:
            doc = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scores = doc.get("scores")
        if not isinstance(scores, dict):
            continue

        before = (scores.get("fundamental"), scores.get("quality"), scores.get("composite"))
        # `quality` mirrors `fundamental` rather than keeping the zero-weight dimension: two
        # tiles side by side showing different numbers for the same idea is the confusion
        # this pass exists to remove. The frontend now renders one of them.
        scores["fundamental"] = canonical
        scores["quality"] = canonical
        composite = _recompute_composite(scores, canonical, None)
        if composite is not None:
            scores["composite"] = composite
            row["composite_score"] = composite
        elif canonical is None:
            scores["composite"] = None

        # The written summary quotes the score, so it has to be rebuilt from the new one or it
        # keeps telling the reader the company "rates excellent (86)".
        try:
            from app.services.summary import build_summary

            doc["ai_summary"] = build_summary(
                name=(doc.get("security") or {}).get("name") or row.get("name") or sym,
                scores=scores,
                ratios=doc.get("ratios") or {},
                signal=doc.get("signal"),
                top_pattern=row.get("top_chart_pattern"),
                insider=doc.get("insider_summary"),
            )
        except Exception:  # noqa: BLE001 - a summary must never fail the reconciliation
            pass

        if (scores.get("fundamental"), scores.get("quality"), scores.get("composite")) != before:
            try:
                cf.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                files += 1
            except OSError:
                continue

    try:
        screener.write_text(json.dumps(rows), encoding="utf-8")
    except OSError:
        log.warning("score-unify: could not write the screener")

    result = {"rows": len(rows), "aligned": aligned, "cleared": cleared, "company_files": files}
    log.info("score-unify: %s", result)
    return result
