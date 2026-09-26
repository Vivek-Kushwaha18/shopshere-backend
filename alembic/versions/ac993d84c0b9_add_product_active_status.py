"""add product active status

Revision ID: ac993d84c0b9
Revises: c99f6a3bcd93
Create Date: 2026-09-21 10:26:58.418201

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ac993d84c0b9"
down_revision: Union[str, Sequence[str], None] = "c99f6a3bcd93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=True,
        ),
    )

    op.execute(
        "UPDATE products SET is_active = TRUE WHERE is_active IS NULL"
    )

    op.alter_column(
        "products",
        "is_active",
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("products", "is_active")