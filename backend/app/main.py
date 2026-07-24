"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import RateLimitMiddleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("Starting %s (env=%s)", settings.project_name, settings.env)

    if settings.seed_on_startup:
        # Reference data only; safe/idempotent. Requires migrations to have run.
        try:
            from app.db.seed import seed_all

            counts = seed_all()
            log.info("Startup seed: %s", counts)
        except Exception as exc:  # pragma: no cover - non-fatal at boot
            log.warning("Startup seed skipped: %s", exc)

    _bootstrap_admin()

    yield
    log.info("Shutting down %s", settings.project_name)


def _bootstrap_admin() -> None:
    """Create the first superuser from env vars if configured and absent."""
    if not (settings.admin_email and settings.admin_password):
        return
    try:
        from app.db.session import session_scope
        from app.services.auth import create_user, get_by_email

        with session_scope() as db:
            if get_by_email(db, settings.admin_email) is None:
                create_user(
                    db,
                    settings.admin_email,
                    settings.admin_password,
                    full_name="Administrator",
                    is_superuser=True,
                )
                log.info("Bootstrapped superuser %s", settings.admin_email)
    except Exception as exc:  # pragma: no cover - non-fatal at boot
        log.warning("Admin bootstrap skipped: %s", exc)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.project_name,
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
