"""Fill the Quality + Risk score legs for names that already have fundamentals.

The web fundamentals backfill originally wrote only the fundamental leg, so ~6.6k expanded
names showed "-" for QUALITY and RISK on their company page. Their ratios are already stored,
so this recomputes both legs locally with the same engine the curated pipeline uses - no
network, no re-fetching - reblends the composite, and re-derives the signal.

Run from backend/:  python ../scripts/backfill_quality_risk.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")  # run from backend/
from app.engines.composite.dimensions import quality_score, risk_score  # noqa: E402
from app.engines.composite.regime_modifier import apply_regime_modifier  # noqa: E402
from app.engines.composite.signals import derive_signal  # noqa: E402
from app.ingestion.tech_refresh import _f, _reblend  # noqa: E402

OUT = Path("../frontend/public/data")


class _Obj:
    """Attribute view over a ratios dict (missing key -> None)."""

    def __init__(self, d: dict):
        object.__setattr__(self, "_d", d or {})

    def __getattr__(self, k):
        return self._d.get(k)


def main() -> int:
    rows = json.loads((OUT / "screener.json").read_text(encoding="utf-8"))
    try:
        regime_map = json.loads(
            (OUT / "macro_regime.json").read_text(encoding="utf-8")
        ).get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}

    cdir = OUT / "company"
    fixed = 0
    for r in rows:
        ps = r.get("provider_symbol")
        if not ps:
            continue
        cf = cdir / f"{ps}.json"
        if not cf.exists():
            continue
        try:
            d = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scores = d.get("scores")
        if not isinstance(scores, dict):
            continue
        if scores.get("quality") is not None and scores.get("risk") is not None:
            continue  # already complete
        ratios = _Obj(d.get("ratios") or {})
        qual, _q = quality_score(ratios)
        risk, _r = risk_score(None, ratios)
        if qual is None and risk is None:
            continue

        fund = _f(scores.get("fundamental"))
        tech = _f(scores.get("technical")) or _f(r.get("technical_score"))
        mom = _f(scores.get("momentum"))
        base, cov, present = _reblend(fund, tech, mom, _f(qual), _f(risk))
        if base is None:
            continue
        comp, _bd = apply_regime_modifier(
            base, regime_map.get(r.get("region")), _f(ratios.debt_to_equity)
        )
        sig = derive_signal(comp, cov, present)

        if qual is not None:
            scores["quality"] = round(qual, 2)
        if risk is not None:
            scores["risk"] = round(risk, 2)
        scores["composite"] = comp
        if isinstance(d.get("signal"), dict):
            d["signal"]["signal_type"] = sig.signal.value
            d["signal"]["label"] = sig.label
        try:
            cf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except OSError:
            continue  # locked/undwritable file - skip it rather than abort the whole repair

        r["composite_score"] = comp
        r["signal"] = sig.signal.value
        r["signal_label"] = sig.label
        fixed += 1

    rows.sort(
        key=lambda x: (x.get("composite_score") is not None, x.get("composite_score") or 0),
        reverse=True,
    )
    (OUT / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    print(f"quality/risk filled for {fixed} names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
