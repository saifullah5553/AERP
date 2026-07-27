"""Macro-regime overlay for the composite score.

A small, bounded nudge applied AFTER the base composite blend so scores respond to the
company's country macro regime — the "dynamic, updates when macro changes, country-relevant"
directive — without letting macro overwhelm company-specific fundamentals. Two legs:

  * health tilt — a bullish regime (high Market Health Score) lifts scores slightly,
    a bearish one lowers them, proportional to how far health sits from neutral (50).
  * rate/leverage interaction — in a falling-rate regime, highly-levered names get a
    small tailwind; in a rising-rate regime they are penalised. Only bites above a D/E
    threshold and scales with leverage.

Every leg is clamped, and the total is clamped to ``MAX_TOTAL`` points. When no regime is
available (or health is unknown) the base score is returned unchanged, so this can never
fabricate a signal — it only tilts an already-computed score. The breakdown is stored for
full transparency and the UI labels regime-derived reads as model-derived.
"""

from __future__ import annotations

MAX_HEALTH = 3.0   # max ± points from the regime health tilt
MAX_RATE = 2.0     # max ± points from the rate/leverage interaction
MAX_TOTAL = 5.0    # overall clamp on the combined nudge
DE_FLOOR = 0.8     # leverage below this is not rate-sensitive enough to adjust
DE_CAP = 2.0       # leverage at/above this gets the full rate weight


def _signal_score(regime: dict, key: str) -> float | None:
    for s in regime.get("signals", []) or []:
        if s.get("key") == key:
            v = s.get("score")
            return float(v) if v is not None else None
    return None


def apply_regime_modifier(
    base: float | None,
    regime: dict | None,
    debt_to_equity: float | None,
) -> tuple[float | None, dict]:
    """Return (adjusted_composite, breakdown). Base unchanged when no usable regime."""
    if base is None or not regime:
        return base, {}

    parts: dict[str, object] = {}
    total = 0.0

    health = regime.get("health")
    if health is not None:
        tilt = (float(health) - 50.0) / 50.0 * MAX_HEALTH
        tilt = max(-MAX_HEALTH, min(MAX_HEALTH, tilt))
        parts["health_tilt"] = round(tilt, 2)
        total += tilt

    rc = _signal_score(regime, "rate_cycle")
    de = debt_to_equity
    if rc is not None and de is not None and de > DE_FLOOR:
        lev = min(1.0, (de - DE_FLOOR) / (DE_CAP - DE_FLOOR))
        # rate_cycle score: falling rates → high (~80, good for leverage); rising → low (~30).
        rate_leg = (rc - 50.0) / 50.0 * MAX_RATE * lev
        rate_leg = max(-MAX_RATE, min(MAX_RATE, rate_leg))
        parts["rate_leverage"] = round(rate_leg, 2)
        total += rate_leg

    if not parts:
        return base, {}

    total = max(-MAX_TOTAL, min(MAX_TOTAL, total))
    adjusted = max(0.0, min(100.0, base + total))
    parts["regime"] = regime.get("regime")
    parts["health"] = health
    parts["total"] = round(total, 2)
    return round(adjusted, 2), parts
