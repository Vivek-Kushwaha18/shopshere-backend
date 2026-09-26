"""add product images

Revision ID: d34e90475e1f
Revises: d46eb06e66d0
Create Date: 2026-09-26 13:24:00.228173

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d34e90475e1f"
down_revision: Union[str, Sequence[str], None] = "d46eb06e66d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # =========================================================
    # PRODUCT IMAGES TABLE
    # =========================================================

    tables = inspector.get_table_names()

    if "product_images" not in tables:
        op.create_table(
            "product_images",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("image_url", sa.String(length=500), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["product_id"],
                ["products.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

        op.create_index(
            "ix_product_images_id",
            "product_images",
            ["id"],
            unique=False,
        )

        op.create_index(
            "ix_product_images_product_id",
            "product_images",
            ["product_id"],
            unique=False,
        )

    # =========================================================
    # CATEGORIES
    # =========================================================

    category_columns = {
        column["name"]
        for column in inspector.get_columns("categories")
    }

    if "description" in category_columns:
        op.alter_column(
            "categories",
            "description",
            existing_type=sa.String(length=500),
            type_=sa.Text(),
            existing_nullable=True,
        )

    if "is_deleted" in category_columns:
        op.drop_column(
            "categories",
            "is_deleted",
        )

    # =========================================================
    # PRODUCTS
    # =========================================================

    product_columns = {
        column["name"]: column
        for column in inspector.get_columns("products")
    }

    # ---------------------------------------------------------
    # original_price
    # ---------------------------------------------------------

    # Production database does not currently have this column.
    if "original_price" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "original_price",
                sa.Numeric(
                    precision=10,
                    scale=2,
                ),
                nullable=True,
            ),
        )

        product_columns["original_price"] = {
            "name": "original_price",
            "type": sa.Numeric(
                precision=10,
                scale=2,
            ),
            "nullable": True,
        }

    # ---------------------------------------------------------
    # name
    # ---------------------------------------------------------

    if "name" in product_columns:
        op.alter_column(
            "products",
            "name",
            existing_type=product_columns["name"]["type"],
            type_=sa.String(length=255),
            existing_nullable=product_columns["name"]["nullable"],
        )

    # ---------------------------------------------------------
    # price
    # ---------------------------------------------------------

    if "price" in product_columns:
        op.alter_column(
            "products",
            "price",
            existing_type=product_columns["price"]["type"],
            type_=sa.Float(),
            existing_nullable=product_columns["price"]["nullable"],
        )

    # ---------------------------------------------------------
    # original_price
    # ---------------------------------------------------------

    if "original_price" in product_columns:
        op.alter_column(
            "products",
            "original_price",
            existing_type=product_columns["original_price"]["type"],
            type_=sa.Float(),
            existing_nullable=product_columns["original_price"]["nullable"],
        )

    # ---------------------------------------------------------
    # rating
    # ---------------------------------------------------------

    if "rating" in product_columns:
        op.alter_column(
            "products",
            "rating",
            existing_type=product_columns["rating"]["type"],
            type_=sa.Float(),
            existing_nullable=product_columns["rating"]["nullable"],
        )

    # ---------------------------------------------------------
    # image
    # ---------------------------------------------------------

    if "image" in product_columns:
        op.drop_column(
            "products",
            "image",
        )

    # ---------------------------------------------------------
    # products name index
    # ---------------------------------------------------------

    product_indexes = inspector.get_indexes("products")

    index_names = {
        index["name"]
        for index in product_indexes
        if index.get("name")
    }

    if "ix_products_name" in index_names:
        op.drop_index(
            "ix_products_name",
            table_name="products",
        )


def downgrade() -> None:
    # This migration is intended for forward synchronization
    # of the existing production schema.
    pass