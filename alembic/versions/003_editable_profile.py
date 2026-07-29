"""add editable user display name

Revision ID: 003_profile
Revises: 002_bill_import
"""

from alembic import op
import sqlalchemy as sa


revision = "003_profile"
down_revision = "002_bill_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
