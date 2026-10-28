
"""add payment refund fields

Revision ID: 6cb350a2c5f5
Revises: c7129b3f6a21
Create Date: 2026-10-28 10:51:32.866212
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic revision identifiers.
revision: str = "6cb350a2c5f5"
down_revision: Union[str, Sequence[str], None] = "c7129b3f6a21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add payment refund tracking fields."""
    op.add_column(
        "payments",
        sa.Column("refund_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("refund_amount", sa.Float(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("refund_status", sa.String(length=30), nullable=True),
    )

    op.create_index(
        op.f("ix_payments_refund_id"),
        "payments",
        ["refund_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payments_refund_status"),
        "payments",
        ["refund_status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove payment refund tracking fields."""
    op.drop_index(
        op.f("ix_payments_refund_status"),
        table_name="payments",
    )
    op.drop_index(
        op.f("ix_payments_refund_id"),
        table_name="payments",
    )

    op.drop_column("payments", "refund_status")
    op.drop_column("payments", "refund_amount")
    op.drop_column("payments", "refund_id")
