"""add category active status

Revision ID: c99f6a3bcd93
Revises: 3677481349c1
Create Date: 2026-09-21 10:17:19.781497

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c99f6a3bcd93"
down_revision: Union[str, Sequence[str], None] = "3677481349c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=True,
        ),
    )

    op.execute(
        "UPDATE categories SET is_active = TRUE WHERE is_active IS NULL"
    )

    op.alter_column(
        "categories",
        "is_active",
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("categories", "is_active")