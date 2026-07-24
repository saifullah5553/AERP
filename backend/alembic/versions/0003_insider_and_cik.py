"""insider summaries + security CIK

Adds ``securities.cik`` (SEC EDGAR id) and the ``insider_summaries`` table.

Revision ID: 0003_insider
Revises: 0002_macro
Create Date: 2026-07-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.corporate import InsiderSummary

revision: str = "0003_insider"
down_revision: str | None = "0002_macro"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("securities", sa.Column("cik", sa.String(length=10), nullable=True))
    op.create_index("ix_securities_cik", "securities", ["cik"])
    InsiderSummary.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    InsiderSummary.__table__.drop(bind=op.get_bind())
    op.drop_index("ix_securities_cik", table_name="securities")
    op.drop_column("securities", "cik")
