"""Per-country Market Regime engine — the dynamic spine of the platform.

Each refresh, this recomputes a market regime (Bullish / Neutral / Bearish) and a
0–100 Market Health Score for every covered country from *live* inputs, so the whole
platform shifts automatically when the macro backdrop changes:

  * Index trend         — the country's benchmark index vs its moving averages
  * Interest-rate cycle — falling rates are supportive, rising restrictive
  * Inflation trend     — easing inflation is supportive
  * Currency trend      — a stable/strengthening local currency is supportive
  * External position   — FX reserves / current account (where available)
  * Commodity env       — for net importers, falling input costs are supportive
  * Market breadth      — average composite score across the market

Pakistan is the flagship (full live macro from Portfolio360: SBP rate, CPI, USD/PKR,
FX reserves, current account, KSE-100). Other markets use the real subset available to
them (index technicals + World Bank macro + commodity trend + breadth). Every number is
real; the regime *label* is a transparent, weighted synthesis — not a prediction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass, MacroIndicatorType
from app.models.macro import MacroIndicator
from app.models.market import Market, Security
from app.models.quote import Quote
from app.models.scoring import Score
from app.models.technical import TechnicalIndicator

log = get_logger(__name__)

# region → (World Bank country code, benchmark index provider_symbol, net-importer?)
REGIONS = {
    "psx": ("PK", None, True),          # index/macro from Portfolio360 live series
    "us": ("US", "^GSPC", False),
    "india": ("IN", "^NSEI", True),
    "gcc": ("SA", "^TASI.SR", False),
    "australia": ("AU", "^AXJO", False),
}
REGION_LABEL = {"psx": "Pakistan", "us": "United States", "india": "India",
                "gcc": "Saudi (Tadawul)", "australia": "Australia",
                "dfm": "Dubai (DFM)"}

# Signal weights (configurable). Renormalized over whichever signals are available.
WEIGHTS = {
    "index_trend": 0.28, "rate_cycle": 0.16, "inflation_trend": 0.14,
    "currency_trend": 0.12, "external": 0.08, "commodity_env": 0.10, "breadth": 0.12,
}


@dataclass(slots=True)
class Signal:
    key: str
    label: str
    value: str
    score: float | None   # 0..100, higher = more supportive
    note: str = ""
    # Period the figure describes. Not decoration: these feeds publish a month or more in
    # arrears, so "CPI Inflation 11.1%" was read as today's inflation when it was June's, and
    # nothing on the card said otherwise. A macro reading without its date is a guess.
    as_of: str = ""


@dataclass(slots=True)
class Regime:
    region: str
    label: str
    regime: str           # Bullish / Neutral / Bearish
    health: float | None  # 0..100
    explanation: str
    signals: list[dict] = field(default_factory=list)


# ── series helpers (Portfolio360 points: [{'t': 'YYYY-MM-DD', 'v': float}, ...]) ──
def _latest(pts: list[dict]) -> float | None:
    for p in reversed(pts or []):
        if p.get("v") is not None:
            return float(p["v"])
    return None


def _latest_date(pts: list[dict]) -> str:
    """'Jun 26' for the newest point that actually carries a value."""
    for p in reversed(pts or []):
        if p.get("v") is not None:
            when = str(p.get("t") or "")[:10]
            try:
                year, month = int(when[:4]), int(when[5:7])
            except (ValueError, IndexError):
                return ""
            names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return f"{names[month - 1]} {str(year)[2:]}"
    return ""


def _value_months_ago(pts: list[dict], months: int) -> float | None:
    clean = [p for p in (pts or []) if p.get("v") is not None]
    if len(clean) <= months:
        return float(clean[0]["v"]) if clean else None
    return float(clean[-1 - months]["v"])


def _direction(latest: float | None, prior: float | None, tol: float = 0.02) -> str:
    if latest is None or prior is None:
        return "—"
    if prior == 0:
        return "→"
    ch = (latest - prior) / abs(prior)
    return "↑" if ch > tol else "↓" if ch < -tol else "→"


def _score_falling_good(latest: float | None, prior: float | None) -> float | None:
    """Falling series is supportive (rates, inflation): ↓ high, ↑ low."""
    d = _direction(latest, prior)
    return {"↓": 80.0, "→": 55.0, "↑": 30.0}.get(d)


def _index_signal(db: Session, provider_symbol: str) -> Signal | None:
    sec = db.scalar(select(Security).where(Security.provider_symbol == provider_symbol))
    if sec is None:
        return None
    t = db.scalar(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.security_id == sec.id)
        .order_by(TechnicalIndicator.date.desc()).limit(1)
    )
    q = db.get(Quote, sec.id)
    close = float(q.price) if q and q.price is not None else None
    s50 = float(t.sma_50) if t and t.sma_50 is not None else None
    s200 = float(t.sma_200) if t and t.sma_200 is not None else None
    if close is None or s50 is None:
        return None
    if s200 is not None and close > s50 > s200:
        score, lbl = 88.0, "Uptrend (above 50 & 200 DMA)"
    elif close > s50:
        score, lbl = 66.0, "Above 50 DMA"
    elif s200 is not None and close < s50 < s200:
        score, lbl = 22.0, "Downtrend (below 50 & 200 DMA)"
    else:
        score, lbl = 42.0, "Below 50 DMA"
    return Signal("index_trend", "Index Trend", lbl, score)


def _wb_change(
    db: Session, country: str, indicator: MacroIndicatorType
) -> tuple[float | None, float | None]:
    rows = db.scalars(
        select(MacroIndicator)
        .where(MacroIndicator.country == country, MacroIndicator.indicator == indicator)
        .order_by(MacroIndicator.period_date.desc()).limit(2)
    ).all()
    latest = float(rows[0].value) if rows and rows[0].value is not None else None
    prior = float(rows[1].value) if len(rows) > 1 and rows[1].value is not None else None
    return latest, prior


def _breadth(db: Session, region: str) -> float | None:
    avg = db.scalar(
        select(func.avg(Score.composite))
        .select_from(Score).join(Security, Score.security_id == Security.id)
        .join(Market, Security.market_id == Market.id)
        .where(Market.region == region, Score.composite.is_not(None),
               Security.asset_class == AssetClass.EQUITY)
    )
    return float(avg) if avg is not None else None


def _regime_label(health: float | None) -> str:
    if health is None:
        return "Neutral"
    return "Bullish" if health >= 60 else "Bearish" if health <= 45 else "Neutral"


def _commodity_env(db: Session, importer: bool) -> Signal | None:
    """Falling commodities support net importers' margins; the reverse for exporters."""
    secs = db.scalars(
        select(Security).where(Security.asset_class == AssetClass.COMMODITY)
    ).all()
    up = down = 0
    for s in secs:
        t = db.scalar(
            select(TechnicalIndicator).where(TechnicalIndicator.security_id == s.id)
            .order_by(TechnicalIndicator.date.desc()).limit(1)
        )
        q = db.get(Quote, s.id)
        close = float(q.price) if q and q.price is not None else None
        s50 = float(t.sma_50) if t and t.sma_50 is not None else None
        if close is None or s50 is None:
            continue
        if close > s50 * 1.02:
            up += 1
        elif close < s50 * 0.98:
            down += 1
    if up + down == 0:
        return None
    falling = down > up
    if importer:
        score = 70.0 if falling else 40.0 if up > down else 55.0
    else:
        score = 62.0 if up > down else 48.0 if falling else 55.0
    lbl = f"{down} inputs easing / {up} rising"
    return Signal("commodity_env", "Commodity Environment", lbl, score)


def _pakistan_signals(pk: dict[str, list[dict]], kse_live: float | None = None) -> list[Signal]:
    out: list[Signal] = []
    # Index trend from KSE-100 series (^KSE not on Yahoo). Trend is computed from the
    # monthly series, but the DISPLAYED level prefers the live index (kse_live) so it
    # matches the World Indices ticker instead of showing a month-end value.
    kse = pk.get("kse100") or []
    if kse:
        latest, ago = _latest(kse), _value_months_ago(kse, 3)
        d = _direction(latest, ago)
        score = {"↑": 82.0, "→": 55.0, "↓": 30.0}.get(d, 55.0)
        disp = kse_live if kse_live else latest
        out.append(Signal("index_trend", "Index Trend (KSE-100)",
                          f"{d} {disp:,.0f}" if disp else "—", score,
                          "vs 3 months ago", _latest_date(kse)))
    rate = pk.get("sbp_policy_rate_pct") or []
    if rate:
        latest, ago = _latest(rate), _value_months_ago(rate, 6)
        out.append(Signal("rate_cycle", "SBP Policy Rate",
                          f"{_direction(latest, ago)} {latest:.1f}%" if latest else "—",
                          _score_falling_good(latest, ago), "vs 6 months ago",
                          _latest_date(rate)))
    cpi = pk.get("cpi_yoy_pct") or []
    if cpi:
        latest, ago = _latest(cpi), _value_months_ago(cpi, 6)
        out.append(Signal("inflation_trend", "CPI Inflation",
                          f"{_direction(latest, ago)} {latest:.1f}%" if latest else "—",
                          _score_falling_good(latest, ago), "vs 6 months ago",
                          _latest_date(cpi)))
    fx = pk.get("usd_pkr") or []
    if fx:
        latest, ago = _latest(fx), _value_months_ago(fx, 6)
        d = _direction(latest, ago)  # ↑ usd_pkr = PKR depreciation = negative
        score = {"↓": 75.0, "→": 62.0, "↑": 35.0}.get(d)
        out.append(Signal("currency_trend", "USD / PKR",
                          f"{d} {latest:.1f}" if latest else "—", score,
                          "rising = PKR weakness", _latest_date(fx)))
    res = pk.get("fx_reserves_musd") or []
    if res:
        latest, ago = _latest(res), _value_months_ago(res, 6)
        d = _direction(latest, ago)
        score = {"↑": 75.0, "→": 55.0, "↓": 35.0}.get(d)
        out.append(Signal("external", "FX Reserves",
                          f"{d} ${latest/1000:.1f}B" if latest else "—", score,
                          "vs 6 months ago"))
    return out


def _synthesize(region: str, signals: list[Signal]) -> Regime:
    scored = [s for s in signals if s.score is not None]
    if scored:
        tw = sum(WEIGHTS.get(s.key, 0.1) for s in scored)
        health = sum(s.score * WEIGHTS.get(s.key, 0.1) for s in scored) / tw if tw else None
    else:
        health = None
    regime = _regime_label(health)
    # Dynamic explanation from the strongest supportive / weakest drags.
    ups = [s.label.lower() for s in scored if s.score and s.score >= 65]
    downs = [s.label.lower() for s in scored if s.score and s.score <= 40]
    parts = [f"{REGION_LABEL.get(region, region)} market regime is {regime.lower()}"
             + (f" ({health:.0f}/100)." if health is not None else ".")]
    if ups:
        parts.append("Supportive: " + ", ".join(ups) + ".")
    if downs:
        parts.append("Headwinds: " + ", ".join(downs) + ".")
    return Regime(region, REGION_LABEL.get(region, region), regime,
                  round(health, 1) if health is not None else None,
                  " ".join(parts), [asdict(s) for s in scored])


def build_macro_regime(
    db: Session,
    pk_macro: dict[str, list[dict]] | None = None,
    pk_kse_live: float | None = None,
) -> dict:
    """One regime per covered country → {'countries': {region: {...}}, ...}."""
    countries: dict[str, dict] = {}
    for region, (wb, index_sym, importer) in REGIONS.items():
        signals: list[Signal] = []
        if region == "psx" and pk_macro:
            signals += _pakistan_signals(pk_macro, pk_kse_live)
        elif index_sym:
            s = _index_signal(db, index_sym)
            if s:
                signals.append(s)
        if region != "psx":  # World Bank rate/inflation for non-PK (annual, coarse)
            rl, rp = _wb_change(db, wb, MacroIndicatorType.REAL_INTEREST_RATE)
            if rl is not None:
                signals.append(Signal("rate_cycle", "Real Interest Rate",
                                      f"{_direction(rl, rp)} {rl:.1f}%",
                                      _score_falling_good(rl, rp), "World Bank, annual"))
            il, ip = _wb_change(db, wb, MacroIndicatorType.CPI_INFLATION)
            if il is not None:
                signals.append(Signal("inflation_trend", "CPI Inflation",
                                      f"{_direction(il, ip)} {il:.1f}%",
                                      _score_falling_good(il, ip), "World Bank, annual"))
        ce = _commodity_env(db, importer)
        if ce:
            signals.append(ce)
        b = _breadth(db, region)
        if b is not None:
            signals.append(Signal("breadth", "Market Breadth", f"avg score {b:.0f}", b,
                                  "avg composite of market"))
        countries[region] = asdict(_synthesize(region, signals))
    # Stamp the build time so the UI (and an operator) can verify the regime is auto-refreshing
    # rather than silently serving a stale merge.
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "countries": countries,
    }
