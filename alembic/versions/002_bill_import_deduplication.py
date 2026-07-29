"""Add an idempotency key for imported bill transactions.

Revision ID: 002_bill_import
Revises: 001_phone_auth
Create Date: 2026-07-29
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "002_bill_import"
down_revision: str | None = "001_phone_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("import_key", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_transactions_import_key",
        "transactions",
        ["import_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_import_key", table_name="transactions")
    op.drop_column("transactions", "import_key")
