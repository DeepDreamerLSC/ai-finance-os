"""add transaction subcategory and tags

Revision ID: 004_tx_classification
Revises: 003_profile
"""

from alembic import op
import sqlalchemy as sa

from app.categories import classify_transaction


revision = "004_tx_classification"
down_revision = "003_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("subcategory", sa.String(length=32), nullable=False, server_default="其他"),
    )
    op.add_column(
        "transactions",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )

    connection = op.get_bind()
    transactions = sa.table(
        "transactions",
        sa.column("id", sa.String()),
        sa.column("category", sa.String()),
        sa.column("subcategory", sa.String()),
        sa.column("tags", sa.JSON()),
    )
    rows = connection.execute(
        sa.text(
            """
            SELECT t.id, t.type, t.category, t.note, t.source,
                   CASE WHEN r.id IS NULL THEN 0 ELSE 1 END AS has_receipt
            FROM transactions AS t
            LEFT JOIN receipts AS r ON r.transaction_id = t.id
            """
        )
    ).mappings()
    for row in rows:
        classification = classify_transaction(
            row["note"],
            row["type"],
            existing_category=row["category"],
            source=row["source"],
            has_receipt=bool(row["has_receipt"]),
        )
        connection.execute(
            transactions.update()
            .where(transactions.c.id == row["id"])
            .values(
                category=classification["category"],
                subcategory=classification["subcategory"],
                tags=classification["tags"],
            )
        )

def downgrade() -> None:
    op.drop_column("transactions", "tags")
    op.drop_column("transactions", "subcategory")
