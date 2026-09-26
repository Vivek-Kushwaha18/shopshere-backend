"""add category timestamps

Revision ID: d46eb06e66d0
Revises: cb57af972c93
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d46eb06e66d0"
down_revision: Union[str, Sequence[str], None] = "cb57af972c93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add created_at temporarily as nullable
    op.add_column(
        "categories",
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    # Add updated_at temporarily as nullable
    op.add_column(
        "categories",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    # Fill timestamps for existing categories
    op.execute(
        """
        UPDATE categories
        SET
            created_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE
            created_at IS NULL
            OR updated_at IS NULL
        """
    )

    # Make created_at required
    op.alter_column(
        "categories",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )

    # Make updated_at required
    op.alter_column(
        "categories",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column(
        "categories",
        "updated_at",
    )

    op.drop_column(
        "categories",
        "created_at",
    )