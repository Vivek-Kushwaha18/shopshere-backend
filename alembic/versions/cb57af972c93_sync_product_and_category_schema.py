"""sync product and category schema

Revision ID: cb57af972c93
Revises: ccdc7851b8f6
Create Date: 2026-09-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cb57af972c93"
down_revision: Union[str, Sequence[str], None] = "ccdc7851b8f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""

    # ---------------------------------------------------------
    # CATEGORIES
    # ---------------------------------------------------------

    # Add soft-delete column safely.
    # Existing rows receive False.
    op.add_column(
        "categories",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # ---------------------------------------------------------
    # PRODUCTS
    # ---------------------------------------------------------

    # New image URL column.
    op.add_column(
        "products",
        sa.Column(
            "image_url",
            sa.String(length=500),
            nullable=True,
        ),
    )

    # Add soft-delete column safely.
    # Existing rows receive False.
    op.add_column(
        "products",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Add created_at safely.
    # Existing products receive the current timestamp.
    op.add_column(
        "products",
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # Add updated_at safely.
    # Existing products receive the current timestamp.
    op.add_column(
        "products",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # Make timestamps required after existing rows
    # have received values.
    op.alter_column(
        "products",
        "created_at",
        nullable=False,
    )

    op.alter_column(
        "products",
        "updated_at",
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade database schema."""

    # Remove product columns added by this migration.
    op.drop_column("products", "updated_at")
    op.drop_column("products", "created_at")
    op.drop_column("products", "is_deleted")
    op.drop_column("products", "image_url")

    # Remove category soft-delete column.
    op.drop_column("categories", "is_deleted")