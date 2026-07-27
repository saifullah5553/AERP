"""AERP management CLI — run the whole pipeline without Celery/broker/auth.

Useful for local runs, demos, and cron jobs. Every command operates directly on
the configured database (``DATABASE_URL``; point it at SQLite for a keyless local
run, e.g. ``DATABASE_URL=sqlite+pysqlite:///./aerp.db``).

Examples:
    python -m app.cli init-db
    python -m app.cli seed
    python -m app.cli ingest-psx
    python -m app.cli ingest-macro
    python -m app.cli compute
    python -m app.cli all                 # seed → ingest everything → compute
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from app.core.logging import get_logger
from app.models.enums import MarketRegion

log = get_logger("aerp.cli")


def _region(value: str | None) -> MarketRegion | None:
    return MarketRegion(value) if value else None


def cmd_init_db(args: argparse.Namespace) -> None:
    """Create all tables (local/dev convenience; production uses Alembic)."""
    from app.db.session import engine
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    log.info("Schema created on %s", engine.url.render_as_string(hide_password=True))


def cmd_seed(args: argparse.Namespace) -> None:
    from app.db.seed import seed_all

    log.info("seed: %s", seed_all())


def cmd_ingest_psx(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.psx_csv import ingest_psx_csv

    with session_scope() as db:
        log.info("ingest-psx: %s", ingest_psx_csv(db))


def cmd_ingest_psx_market(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.psx_market import ingest_psx_market

    with session_scope() as db:
        ingest_psx_market(
            db,
            with_history=not getattr(args, "no_history", False),
            history_limit=args.limit,
        )


def cmd_ingest_macro(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.macro import WorldBankClient, ingest_macro

    with session_scope() as db:
        log.info("ingest-macro: %s", ingest_macro(db, WorldBankClient()))


def cmd_ingest_quotes(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import refresh_quotes
    from app.ingestion.registry import ProviderRegistry

    with session_scope() as db:
        r = refresh_quotes(db, ProviderRegistry(), region=_region(args.region), limit=args.limit)
        log.info("ingest-quotes: requested=%d resolved=%d", r.requested, r.resolved)


def cmd_backfill(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import backfill_daily
    from app.ingestion.registry import ProviderRegistry

    with session_scope() as db:
        n = backfill_daily(db, ProviderRegistry(), region=_region(args.region), limit=args.limit)
        log.info("backfill: %d bars", n)


def cmd_ingest_fundamentals(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import ingest_fundamentals
    from app.ingestion.registry import ProviderRegistry

    with session_scope() as db:
        log.info("ingest-fundamentals: %s",
                 ingest_fundamentals(db, ProviderRegistry(), region=_region(args.region),
                                     limit=args.limit))


def cmd_load_universe(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import load_universe
    from app.ingestion.registry import ProviderRegistry

    providers = args.providers.split(",") if args.providers else None
    with session_scope() as db:
        log.info("load-universe: %s", load_universe(db, ProviderRegistry(), providers))


def cmd_load_us_universe(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.us_universe import (
        US_LARGE_CAPS,
        SECClient,
        ingest_us_universe,
        load_sp500,
    )

    symbols = sectors = None
    if getattr(args, "curated", False):
        sp = load_sp500()
        sectors = {r["symbol"]: r["sector"] for r in sp if r.get("sector")}
        symbols = sorted({r["symbol"] for r in sp} | set(US_LARGE_CAPS))
    with session_scope() as db:
        log.info(
            "load-us-universe: %s",
            ingest_us_universe(db, SECClient(), limit=args.limit, symbols=symbols, sectors=sectors),
        )


def cmd_load_markets(args: argparse.Namespace) -> None:
    """Load curated India / GCC / Australia / forex / commodity / crypto universes."""
    from app.db.session import session_scope
    from app.ingestion.universe_curated import load_curated_universe

    with session_scope() as db:
        log.info("load-markets: %s", load_curated_universe(db))


def cmd_ingest_insider(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.insider import EdgarClient, ingest_insider

    with session_scope() as db:
        log.info("ingest-insider: %s", ingest_insider(db, EdgarClient(), limit=args.limit))


def cmd_ingest_estimates(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.estimates import ingest_estimates

    with session_scope() as db:
        ingest_estimates(db, region=_region(args.region), limit=args.limit)


def cmd_refresh_prices(args: argparse.Namespace) -> None:
    """Patch price fields in the exported snapshot via Yahoo chart v8 (keyless, CI-friendly).
    Does not touch the DB — updates screener.json + company/*.json prices in place."""
    from app.ingestion.price_refresh import refresh_prices

    out = args.out or "../frontend/public/data"
    log.info("refresh-prices: %s", refresh_prices(out, limit=args.limit))


def cmd_ingest_profiles(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.profiles import ingest_profiles

    with session_scope() as db:
        ingest_profiles(db, region=_region(args.region), limit=args.limit)


def cmd_ingest_yahoo_insider(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.yahoo_insider import ingest_yahoo_insider

    with session_scope() as db:
        ingest_yahoo_insider(db, region=_region(args.region), limit=args.limit)


def cmd_ingest_psx_insider_api(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.psx_insider_api import ingest_psx_insider_api

    with session_scope() as db:
        ingest_psx_insider_api(db, limit=args.limit or 500)


def cmd_ingest_psx_insider(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.psx_insider import ingest_psx_insider

    with session_scope() as db:
        log.info("ingest-psx-insider: %s", ingest_psx_insider(db))


def cmd_ingest_news(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.news import GoogleNewsClient, ingest_news

    with session_scope() as db:
        log.info("ingest-news: %s", ingest_news(db, GoogleNewsClient(), limit=args.limit))


def cmd_compute(args: argparse.Namespace) -> None:
    """Run every analytics engine in dependency order."""
    from app.db.session import session_scope
    from app.engines.composite.engine import compute_all as composite_all
    from app.engines.forex.engine import compute_all as forex_all
    from app.engines.fundamental.engine import compute_all as fundamental_all
    from app.engines.insider.engine import compute_all as insider_all
    from app.engines.pabrai.engine import compute_all as pabrai_all
    from app.engines.patterns.engine import compute_all as patterns_all
    from app.engines.technical.engine import compute_all as technical_all

    with session_scope() as db:
        log.info("fundamentals: %s", fundamental_all(db, limit=args.limit))
        log.info("forex: %s", forex_all(db, limit=args.limit))
        log.info("technical: %s", technical_all(db, limit=args.limit))
        log.info("patterns: %s", patterns_all(db, limit=args.limit))
        log.info("insider: %s", insider_all(db, limit=args.limit))
        log.info("composite: %s", composite_all(db, limit=args.limit))
        # Independent Pabrai checklist score (runs after composite creates Score rows).
        log.info("pabrai: %s", pabrai_all(db, limit=args.limit))


def _regime_is_empty(country: dict | None) -> bool:
    """A regime entry carries no real signal (blank health and no signals)."""
    if not country:
        return True
    return country.get("health") is None and not country.get("signals")


def _merge_regime(fresh: dict, path) -> dict:
    """Keep a previously-populated country regime when this run couldn't populate it
    (a PSX-only CI refresh otherwise blanks US/India/GCC/Australia)."""
    import json

    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return fresh
    old_countries = old.get("countries", {}) if isinstance(old, dict) else {}
    countries = dict(fresh.get("countries", {}))
    for region, prev in old_countries.items():
        if _regime_is_empty(countries.get(region)) and not _regime_is_empty(prev):
            countries[region] = prev
    return {**fresh, "countries": countries}


def _merge_sector_stats(fresh: dict, path) -> dict:
    """Preserve a region's prior sector stats when this run produced none for it."""
    import json

    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return fresh
    if not isinstance(old, dict):
        return fresh
    merged = dict(fresh)
    for region, stats in old.items():
        if stats and not merged.get(region):
            merged[region] = stats
    return merged


def cmd_export_static(args: argparse.Namespace) -> None:
    """Export the computed data as static JSON for a backend-less Pages demo."""
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from app.db.session import session_scope
    from app.services.company import get_company
    from app.services.pulse import pulse_from_screener_dicts
    from app.services.raw_materials import build_raw_materials
    from app.services.screener import ScreenerFilters, query_screener

    out = Path(args.out or "../frontend/public/data")
    (out / "company").mkdir(parents=True, exist_ok=True)
    merge = not getattr(args, "no_merge", False)

    with session_scope() as db:
        # Only securities with a real composite score make the demo meaningful.
        rows, total = query_screener(
            db, ScreenerFilters(min_composite=0, sort_by="composite_score"), 0, 5000
        )
        fresh = [r.model_dump(mode="json") for r in rows]

        # Keep only the curated crypto set — a full `cmd_all` loads the whole Binance
        # universe (~470 pairs), which would flood an equity-research terminal with obscure
        # altcoins. Filter both the screener rows and the company-file source list.
        from app.ingestion.universe_curated import CRYPTO

        _curated_crypto = {sym for sym, _ in CRYPTO}

        def _keep_row(r: dict) -> bool:
            if r.get("asset_class") != "crypto":
                return True
            return str(r.get("provider_symbol", "")).split("-")[0] in _curated_crypto

        fresh = [r for r in fresh if _keep_row(r)]
        _kept = {r["provider_symbol"] for r in fresh}
        rows = [r for r in rows if r.provider_symbol in _kept]

        # Merge with any existing snapshot, keyed by provider_symbol: rows this run
        # produced win; rows only in the old snapshot are preserved. This lets the
        # free CI refresh (PSX-only, since Yahoo 429s on datacenter IPs) update PSX
        # without wiping US rows that were populated locally from a residential IP.
        screener_path = out / "screener.json"
        if merge and screener_path.exists():
            try:
                old = json.loads(screener_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                old = []
            by_symbol = {r.get("provider_symbol"): r for r in old}
            for r in fresh:
                by_symbol[r.get("provider_symbol")] = r
            merged = list(by_symbol.values())
        else:
            merged = fresh
        merged.sort(
            key=lambda r: (r.get("composite_score") is not None, r.get("composite_score") or 0),
            reverse=True,
        )

        # Cross-cutting engines (computed before writing the screener so the swing
        # score can be injected into its rows). All recompute each refresh.
        from app.ingestion.portfolio360 import Portfolio360Client
        from app.services.macro_regime import build_macro_regime
        from app.services.sectors import build_sector_stats
        from app.services.swing import build_swing

        pk_macro = None
        try:
            pk_macro = Portfolio360Client().pk_macro()
        except Exception as exc:  # network optional; regime falls back to DB signals
            log.warning("Portfolio360 PK macro fetch failed: %s", exc)
        regime = build_macro_regime(db, pk_macro)
        sector_stats = build_sector_stats(db)
        # CI refreshes are PSX-only (Yahoo 429s on runners), so a fresh regime/sector run
        # only populates PSX. Preserve previously-computed regions from the committed
        # snapshot instead of blanking them (same spirit as the screener/swing merge).
        if merge:
            regime = _merge_regime(regime, out / "macro_regime.json")
            sector_stats = _merge_sector_stats(sector_stats, out / "sector_stats.json")
        raw_materials = build_raw_materials(out / "company")
        swing = build_swing(db, sector_stats, regime, raw_materials)

        # Inject the swing score into each screener row, PRESERVING a prior value when
        # this run didn't recompute it (CI is PSX-only → don't wipe other markets).
        by_sym = swing["by_symbol"]
        for r in merged:
            v = by_sym.get(r.get("provider_symbol"))
            if v is not None:
                r["swing_score"] = v
            elif "swing_score" not in r:
                r["swing_score"] = None

        # Merge swing.json the same way (this run's entries win; others preserved).
        swing_path = out / "swing.json"
        ranked = swing["ranked"]
        if merge and swing_path.exists():
            try:
                old = json.loads(swing_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                old = []
            by = {r.get("provider_symbol"): r for r in old}
            for r in ranked:
                by[r["provider_symbol"]] = r
            ranked = sorted(by.values(), key=lambda r: r.get("swing_score") or 0, reverse=True)

        screener_path.write_text(json.dumps(merged), encoding="utf-8")
        (out / "pulse.json").write_text(
            json.dumps(pulse_from_screener_dicts(merged)), encoding="utf-8"
        )
        (out / "macro_regime.json").write_text(json.dumps(regime), encoding="utf-8")
        (out / "sector_stats.json").write_text(json.dumps(sector_stats), encoding="utf-8")
        (out / "raw_materials.json").write_text(json.dumps(raw_materials), encoding="utf-8")
        swing_path.write_text(json.dumps(ranked), encoding="utf-8")

        # Catalyst calendar (PK economic events + PSX announcements/corporate actions).
        from app.services.catalysts import build_catalysts

        try:
            (out / "catalysts.json").write_text(json.dumps(build_catalysts()), encoding="utf-8")
        except Exception as exc:  # network optional
            log.warning("catalysts export failed: %s", exc)

        exported = 0
        for r in rows:
            detail = get_company(db, r.provider_symbol)
            if detail is None:
                continue
            (out / "company" / f"{r.provider_symbol}.json").write_text(
                json.dumps(detail.model_dump(mode="json")), encoding="utf-8"
            )
            exported += 1
        # Company files for securities only in the old snapshot are left in place.
        company_files = len(list((out / "company").glob("*.json")))
        (out / "meta.json").write_text(
            json.dumps({
                "generated_at": datetime.now(UTC).isoformat(),
                "securities": len(merged),
                "companies": company_files,
                "mode": "static-demo",
            }),
            encoding="utf-8",
        )
    log.info(
        "export-static: %d rows this run, %d total after merge, %d company files → %s",
        total, len(merged), company_files, out,
    )


def _safe(name: str, fn: Callable[[], None]) -> None:
    """Run one pipeline step, logging and swallowing failures so a single flaky external
    source (a transient 5xx, a rate-limit) can't abort a full multi-hour rebuild."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - resilience: continue the pipeline
        log.warning("cmd_all: step '%s' failed (continuing): %s", name, exc)


def cmd_all(args: argparse.Namespace) -> None:
    """Full local pipeline: schema → seed → ingest everything → compute.

    Schema/seed and the final compute are hard (must run); every network-dependent
    ingestion step is wrapped so a transient upstream failure degrades coverage rather
    than aborting the whole run (the merge-preserving export then keeps prior data)."""
    cmd_init_db(args)
    cmd_seed(args)
    ns = argparse.Namespace
    rl = ns(region=None, limit=None)  # region=all, no limit — reused by the region-aware steps
    steps: list[tuple[str, Callable[[], None]]] = [
        ("load-universe", lambda: cmd_load_universe(ns(providers="binance,psx"))),
        ("load-us-universe", lambda: cmd_load_us_universe(ns(limit=None, curated=True))),
        ("load-markets", lambda: cmd_load_markets(args)),
        ("ingest-psx", lambda: cmd_ingest_psx(args)),
        ("ingest-psx-market", lambda: cmd_ingest_psx_market(ns(limit=None, no_history=False))),
        ("ingest-macro", lambda: cmd_ingest_macro(args)),
        ("ingest-psx-insider", lambda: cmd_ingest_psx_insider(args)),
        ("ingest-psx-insider-api", lambda: cmd_ingest_psx_insider_api(ns(limit=500))),
        ("ingest-yahoo-insider", lambda: cmd_ingest_yahoo_insider(rl)),
        ("ingest-estimates", lambda: cmd_ingest_estimates(rl)),
        ("ingest-profiles", lambda: cmd_ingest_profiles(rl)),
        ("ingest-quotes", lambda: cmd_ingest_quotes(rl)),
        ("backfill", lambda: cmd_backfill(rl)),
        ("ingest-fundamentals", lambda: cmd_ingest_fundamentals(rl)),
    ]
    for name, fn in steps:
        _safe(name, fn)
    cmd_compute(ns(limit=None))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aerp", description="AERP management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func: Callable, *, region=False, limit=False, providers=False):
        p = sub.add_parser(name)
        if region:
            p.add_argument("--region", default=None, help="us|india|gcc|psx|global")
        if limit:
            p.add_argument("--limit", type=int, default=None)
        if providers:
            p.add_argument("--providers", default=None, help="comma list, e.g. binance,psx")
        p.set_defaults(func=func)
        return p

    add("init-db", cmd_init_db)
    add("seed", cmd_seed)
    add("load-universe", cmd_load_universe, providers=True)
    usu = add("load-us-universe", cmd_load_us_universe, limit=True)
    usu.add_argument("--curated", action="store_true", help="S&P 500 + large-cap allowlist")
    add("load-markets", cmd_load_markets)
    add("ingest-psx", cmd_ingest_psx)
    psxm = add("ingest-psx-market", cmd_ingest_psx_market, limit=True)
    psxm.add_argument("--no-history", action="store_true", help="quotes+names only")
    add("ingest-macro", cmd_ingest_macro)
    add("ingest-quotes", cmd_ingest_quotes, region=True, limit=True)
    add("backfill", cmd_backfill, region=True, limit=True)
    add("ingest-fundamentals", cmd_ingest_fundamentals, region=True, limit=True)
    add("ingest-insider", cmd_ingest_insider, limit=True)
    add("ingest-yahoo-insider", cmd_ingest_yahoo_insider, region=True, limit=True)
    add("ingest-estimates", cmd_ingest_estimates, region=True, limit=True)
    add("ingest-profiles", cmd_ingest_profiles, region=True, limit=True)
    add("ingest-psx-insider", cmd_ingest_psx_insider)
    add("ingest-psx-insider-api", cmd_ingest_psx_insider_api, limit=True)
    add("ingest-news", cmd_ingest_news, limit=True)
    add("compute", cmd_compute, limit=True)
    export = sub.add_parser("export-static")
    export.add_argument("--out", default=None, help="output dir (default ../frontend/public/data)")
    export.add_argument("--no-merge", action="store_true", help="overwrite; no merge")
    export.set_defaults(func=cmd_export_static)
    rp = add("refresh-prices", cmd_refresh_prices, limit=True)
    rp.add_argument("--out", default=None, help="snapshot dir (default ../frontend/public/data)")
    add("all", cmd_all)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
