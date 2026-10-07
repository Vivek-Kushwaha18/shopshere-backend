"""add parent category

Revision ID: 178a1caa402e
Revises: 97f662216230
Create Date: 2026-10-06 21:18:50.218766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "178a1caa402e"
down_revision: Union[str, Sequence[str], None] = "97f662216230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "categories",
        sa.Column(
            "parent_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        op.f("ix_categories_parent_id"),
        "categories",
        ["parent_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_categories_parent_id_categories",
        "categories",
        "categories",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_categories_parent_id_categories",
        "categories",
        type_="foreignkey",
    )

    op.drop_index(
        op.f("ix_categories_parent_id"),
        table_name="categories",
    )

    op.drop_column(
        "categories",
        "parent_id",
    )