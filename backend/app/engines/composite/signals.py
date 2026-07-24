"""Map a composite score to an actionable signal.

Thresholds are explicit and the confidence reflects how much data backed the
score (coverage) and how decisively the score sits inside its band.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import SignalType

# (lower_bound_inclusive, signal, short label)
_BANDS: list[tuple[float, SignalType, str]] = [
    (80.0, SignalType.STRONG_BUY, "Strong Buy"),
    (65.0, SignalType.BUY, "Buy"),
    (45.0, SignalType.HOLD, "Hold"),
    (30.0, SignalType.SELL, "Sell"),
    (0.0, SignalType.STRONG_SELL, "Strong Sell"),
]


@dataclass(slots=True)
class SignalResult:
    signal: SignalType
    label: str
    confidence: float
    rationale: str


def derive_signal(composite: float, coverage: float, components: dict[str, float]) -> SignalResult:
    signal, label = SignalType.HOLD, "Hold"
    for lower, sig, lbl in _BANDS:
        if composite >= lower:
            signal, label = sig, lbl
            break

    # Confidence: data coverage tempered by proximity to the nearest band edge
    # (scores parked on a boundary are less decisive).
    edges = [b[0] for b in _BANDS] + [100.0]
    nearest = min(abs(composite - e) for e in edges)
    decisiveness = min(1.0, nearest / 10.0)
    confidence = round(coverage * (0.6 + 0.4 * decisiveness), 3)

    ranked = sorted(components.items(), key=lambda kv: kv[1], reverse=True)
    drivers = ", ".join(f"{k} {v:.0f}" for k, v in ranked[:3])
    rationale = f"Composite {composite:.0f}/100 → {label}. Top drivers: {drivers}."
    return SignalResult(signal, label, confidence, rationale)
