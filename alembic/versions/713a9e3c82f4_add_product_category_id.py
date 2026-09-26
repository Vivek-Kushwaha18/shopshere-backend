from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "713a9e3c82f4"
down_revision: Union[str, Sequence[str], None] = "6483e3a86b56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # =========================================================
    # CHECK PRODUCTS COLUMNS
    # =========================================================

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    # =========================================================
    # ADD category_id
    # =========================================================

    if "category_id" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "category_id",
                sa.Integer(),
                nullable=True,
            ),
        )

    # =========================================================
    # COPY MATCHING CATEGORY DATA
    # =========================================================

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    if "category" in product_columns:
        op.execute(
            text(
                """
                UPDATE products AS p
                SET category_id = c.id
                FROM categories AS c
                WHERE p.category_id IS NULL
                  AND p.category IS NOT NULL
                  AND LOWER(TRIM(p.category))
                      = LOWER(TRIM(c.name))
                """
            )
        )

    # =========================================================
    # CREATE FOREIGN KEY
    # =========================================================

    foreign_keys = inspector.get_foreign_keys("products")

    category_fk_exists = any(
        fk.get("constrained_columns") == ["category_id"]
        and fk.get("referred_table") == "categories"
        for fk in foreign_keys
    )

    if not category_fk_exists:
        op.create_foreign_key(
            "fk_products_category_id_categories",
            "products",
            "categories",
            ["category_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # =========================================================
    # REMOVE OLD category COLUMN
    # =========================================================

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    if "category" in product_columns:
        op.drop_column(
            "products",
            "category",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    # Restore old category column if needed.
    if "category" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "category",
                sa.String(length=255),
                nullable=True,
            ),
        )

    # Remove foreign key.
    foreign_keys = inspector.get_foreign_keys("products")

    category_fk_exists = any(
        fk.get("constrained_columns") == ["category_id"]
        and fk.get("referred_table") == "categories"
        for fk in foreign_keys
    )

    if category_fk_exists:
        op.drop_constraint(
            "fk_products_category_id_categories",
            "products",
            type_="foreignkey",
        )

    # Remove category_id.
    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    if "category_id" in product_columns:
        op.drop_column(
            "products",
            "category_id",
        )