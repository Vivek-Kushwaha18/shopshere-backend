"""sync product and category schema

Revision ID: cb57af972c93
Revises: ccdc7851b8f6
Create Date: 2026-09-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "cb57af972c93"
down_revision: Union[str, Sequence[str], None] = "ccdc7851b8f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # =========================================================
    # CATEGORIES
    # =========================================================

    category_columns = {
        column["name"]
        for column in inspector.get_columns("categories")
    }

    if "is_deleted" not in category_columns:
        op.add_column(
            "categories",
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # =========================================================
    # PRODUCTS
    # =========================================================

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    # ---------------------------------------------------------
    # image_url
    # ---------------------------------------------------------

    if "image_url" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "image_url",
                sa.String(length=500),
                nullable=True,
            ),
        )

    # ---------------------------------------------------------
    # is_deleted
    # ---------------------------------------------------------

    if "is_deleted" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # ---------------------------------------------------------
    # created_at
    # ---------------------------------------------------------

    if "created_at" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.now(),
            ),
        )

    # ---------------------------------------------------------
    # updated_at
    # ---------------------------------------------------------

    if "updated_at" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.now(),
            ),
        )

    # Re-read product columns after possible additions.
    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    # =========================================================
    # FIX EXISTING NULL TIMESTAMPS
    # =========================================================

    if "created_at" in product_columns:
        op.execute(
            """
            UPDATE products
            SET created_at = NOW()
            WHERE created_at IS NULL
            """
        )

        op.alter_column(
            "products",
            "created_at",
            nullable=False,
        )

    if "updated_at" in product_columns:
        op.execute(
            """
            UPDATE products
            SET updated_at = NOW()
            WHERE updated_at IS NULL
            """
        )

        op.alter_column(
            "products",
            "updated_at",
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    category_columns = {
        column["name"]
        for column in inspector.get_columns("categories")
    }

    if "updated_at" in product_columns:
        op.drop_column("products", "updated_at")

    if "created_at" in product_columns:
        op.drop_column("products", "created_at")

    if "is_deleted" in product_columns:
        op.drop_column("products", "is_deleted")

    if "image_url" in product_columns:
        op.drop_column("products", "image_url")

    if "is_deleted" in category_columns:
        op.drop_column("categories", "is_deleted")