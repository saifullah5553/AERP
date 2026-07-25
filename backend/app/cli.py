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
    from app.engines.patterns.engine import compute_all as patterns_all
    from app.engines.technical.engine import compute_all as technical_all

    with session_scope() as db:
        log.info("fundamentals: %s", fundamental_all(db, limit=args.limit))
        log.info("forex: %s", forex_all(db, limit=args.limit))
        log.info("technical: %s", technical_all(db, limit=args.limit))
        log.info("patterns: %s", patterns_all(db, limit=args.limit))
        log.info("insider: %s", insider_all(db, limit=args.limit))
        log.info("composite: %s", composite_all(db, limit=args.limit))


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
        screener_path.write_text(json.dumps(merged), encoding="utf-8")

        # Market pulse from the merged (all-market) snapshot.
        (out / "pulse.json").write_text(
            json.dumps(pulse_from_screener_dicts(merged)), encoding="utf-8"
        )

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

        # Raw-material cost-trend map (built from the commodity company files).
        (out / "raw_materials.json").write_text(
            json.dumps(build_raw_materials(out / "company")), encoding="utf-8"
        )
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


def cmd_all(args: argparse.Namespace) -> None:
    """Full local pipeline: schema → seed → ingest everything → compute."""
    cmd_init_db(args)
    cmd_seed(args)
    cmd_load_universe(argparse.Namespace(providers="binance,psx"))
    cmd_load_us_universe(argparse.Namespace(limit=None, curated=True))
    cmd_load_markets(args)
    cmd_ingest_psx(args)
    cmd_ingest_psx_market(argparse.Namespace(limit=None, no_history=False))
    cmd_ingest_macro(args)
    cmd_ingest_psx_insider(args)
    cmd_ingest_quotes(argparse.Namespace(region=None, limit=None))
    cmd_backfill(argparse.Namespace(region=None, limit=None))
    cmd_ingest_fundamentals(argparse.Namespace(region=None, limit=None))
    cmd_compute(argparse.Namespace(limit=None))


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
    add("ingest-psx-insider", cmd_ingest_psx_insider)
    add("ingest-news", cmd_ingest_news, limit=True)
    add("compute", cmd_compute, limit=True)
    export = sub.add_parser("export-static")
    export.add_argument("--out", default=None, help="output dir (default ../frontend/public/data)")
    export.add_argument("--no-merge", action="store_true", help="overwrite; no merge")
    export.set_defaults(func=cmd_export_static)
    add("all", cmd_all)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
