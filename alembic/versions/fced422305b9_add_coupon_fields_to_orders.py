"""add coupon fields to orders

Revision ID: fced422305b9
Revises: 6120fed9929e
Create Date: 2026-10-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fced422305b9"
down_revision: Union[str, Sequence[str], None] = "6120fed9929e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "discount_amount",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "orders",
        sa.Column(
            "coupon_code",
            sa.String(length=50),
            nullable=True,
        ),
    )

    op.alter_column(
        "orders",
        "discount_amount",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column(
        "orders",
        "coupon_code",
    )

    op.drop_column(
        "orders",
        "discount_amount",
    )