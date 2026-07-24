"""macro indicators table

Adds ``macro_indicators`` (country economic data used as forex fundamentals).
Created from the ORM table definition so names/types match the model exactly.

Revision ID: 0002_macro
Revises: 0001_initial
Create Date: 2026-07-24
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.models.macro import MacroIndicator

revision: str = "0002_macro"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    MacroIndicator.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    MacroIndicator.__table__.drop(bind=op.get_bind())
