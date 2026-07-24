"""Rule-based company summary generator.

Produces a plain-language narrative strictly from computed data (scores, ratios,
patterns, signal) — no external LLM and nothing invented. Every sentence is
traceable to a stored value, so the "AI summary" is explainable and reproducible.
(A genuine LLM pass can be layered on later behind a provider key.)
"""

from __future__ import annotations

from typing import Any


def _grade(score: float | None) -> str:
    if score is None:
        return "not yet rated"
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "strong"
    if score >= 45:
        return "average"
    if score >= 30:
        return "weak"
    return "poor"


def _pct(v: float | None) -> str | None:
    return None if v is None else f"{v * 100:.1f}%"


def build_summary(
    name: str,
    scores: dict[str, Any] | None,
    ratios: dict[str, Any] | None,
    signal: dict[str, Any] | None,
    top_pattern: str | None,
) -> str:
    parts: list[str] = []
    comp = (scores or {}).get("composite")

    if comp is None:
        parts.append(
            f"{name} does not yet have enough ingested data for a composite rating."
        )
    else:
        parts.append(
            f"{name} scores {comp:.0f}/100 overall — a {_grade(comp)} composite profile."
        )
        fund = (scores or {}).get("fundamental")
        tech = (scores or {}).get("technical")
        if fund is not None and tech is not None:
            lead = "fundamentals" if fund >= tech else "technicals"
            parts.append(
                f"Fundamentals rate {_grade(fund)} ({fund:.0f}) and technicals "
                f"{_grade(tech)} ({tech:.0f}); the {lead} lead the picture."
            )

    if ratios:
        bits: list[str] = []
        roe = _pct(ratios.get("roe"))
        if roe:
            bits.append(f"ROE {roe}")
        nm = _pct(ratios.get("net_margin"))
        if nm:
            bits.append(f"net margin {nm}")
        de = ratios.get("debt_to_equity")
        if de is not None:
            bits.append(f"debt/equity {de:.2f}")
        rg = _pct(ratios.get("revenue_growth"))
        if rg:
            bits.append(f"revenue growth {rg}")
        if bits:
            parts.append("Key metrics: " + ", ".join(bits) + ".")

    if top_pattern:
        pretty = top_pattern.replace("_", " ")
        parts.append(f"The most prominent active chart pattern is a {pretty}.")

    if signal and signal.get("label"):
        conf = signal.get("confidence")
        conf_txt = f" (confidence {conf:.0%})" if isinstance(conf, int | float) else ""
        parts.append(f"Current signal: {signal['label']}{conf_txt}.")

    parts.append(
        "This summary is generated from computed metrics only; it is not investment advice."
    )
    return " ".join(parts)
