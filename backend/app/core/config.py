"""Application settings, loaded from environment variables.

All configuration flows through this single ``settings`` object. Nothing in the
codebase reads ``os.environ`` directly — that keeps configuration typed,
validated, and discoverable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ───────────────────────────────────────────────────
    env: str = Field(default="development", alias="AERP_ENV")
    debug: bool = Field(default=True, alias="AERP_DEBUG")
    secret_key: str = Field(default="dev-insecure-change-me", alias="AERP_SECRET_KEY")
    api_v1_prefix: str = Field(default="/api/v1", alias="AERP_API_V1_PREFIX")
    project_name: str = "AERP — AI Equity Research Platform"

    # Comma-separated in the env; parsed to a list below.
    cors_origins_raw: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        alias="AERP_CORS_ORIGINS",
    )

    seed_on_startup: bool = Field(default=True, alias="AERP_SEED_ON_STARTUP")

    # Folder of PSX financial CSVs (from the stockanalysis.com scraper) to ingest
    # as fundamentals. Files are named <TICKER>_{Income_Statement,Balance_Sheet,
    # Cash_Flow,Ratios}.csv.
    psx_csv_dir: str = Field(default="data/psx_csv", alias="AERP_PSX_CSV_DIR")

    # CSV of PSX insider/director transactions (from Sarmaaya/PSX). Columns are
    # matched flexibly: symbol, insider, date, type (buy/sell), shares, price.
    psx_insider_csv: str = Field(
        default="data/psx_insider.csv", alias="AERP_PSX_INSIDER_CSV"
    )

    # ── Auth ──────────────────────────────────────────────────
    jwt_algorithm: str = Field(default="HS256", alias="AERP_JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=60 * 24, alias="AERP_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    # Optional first-superuser bootstrap (created at startup if absent).
    admin_email: str | None = Field(default=None, alias="AERP_ADMIN_EMAIL")
    admin_password: str | None = Field(default=None, alias="AERP_ADMIN_PASSWORD")

    # ── Rate limiting ─────────────────────────────────────────
    rate_limit_per_minute: int = Field(default=120, alias="AERP_RATE_LIMIT_PER_MINUTE")

    # ── PostgreSQL ────────────────────────────────────────────
    postgres_user: str = Field(default="aerp", alias="POSTGRES_USER")
    postgres_password: str = Field(default="aerp", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="aerp", alias="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    # Full URL wins if provided (e.g. Render supplies one).
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    # ── Redis ─────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── Data providers (Phase 2) ──────────────────────────────
    fmp_api_key: str | None = Field(default=None, alias="FMP_API_KEY")
    twelve_data_api_key: str | None = Field(default=None, alias="TWELVE_DATA_API_KEY")
    eodhd_api_key: str | None = Field(default=None, alias="EODHD_API_KEY")

    # ── Derived values ────────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """SQLAlchemy URL using the psycopg (v3) driver."""
        if self.database_url_override:
            # Normalise the common `postgres://` form Render/Heroku hand out.
            url = self.database_url_override
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            return url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()


settings = get_settings()
