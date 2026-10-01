"""make product and category slugs required

Revision ID: 412fa732c067
Revises: 09f2afe5ff48
Create Date: 2026-10-01 10:36:35.486110

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import re
import unicodedata


revision: str = "412fa732c067"
down_revision: Union[str, Sequence[str], None] = "09f2afe5ff48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    value = value.strip("-")

    return value or "item"


def get_unique_slug(connection, table_name: str, base_slug: str, current_id: int) -> str:
    slug = base_slug
    counter = 2

    while True:
        result = connection.execute(
            sa.text(
                f"""
                SELECT id
                FROM {table_name}
                WHERE slug = :slug
                AND id != :current_id
                LIMIT 1
                """
            ),
            {
                "slug": slug,
                "current_id": current_id,
            },
        ).fetchone()

        if result is None:
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1


def upgrade() -> None:
    connection = op.get_bind()

    # ---------------------------------------------------------
    # Fill missing category slugs
    # ---------------------------------------------------------
    categories = connection.execute(
        sa.text(
            """
            SELECT id, name
            FROM categories
            WHERE slug IS NULL
            ORDER BY id
            """
        )
    ).fetchall()

    for category in categories:
        base_slug = slugify(category.name)

        unique_slug = get_unique_slug(
            connection,
            "categories",
            base_slug,
            category.id,
        )

        connection.execute(
            sa.text(
                """
                UPDATE categories
                SET slug = :slug
                WHERE id = :id
                """
            ),
            {
                "slug": unique_slug,
                "id": category.id,
            },
        )

    # ---------------------------------------------------------
    # Fill missing product slugs
    # ---------------------------------------------------------
    products = connection.execute(
        sa.text(
            """
            SELECT id, name
            FROM products
            WHERE slug IS NULL
            ORDER BY id
            """
        )
    ).fetchall()

    for product in products:
        base_slug = slugify(product.name)

        unique_slug = get_unique_slug(
            connection,
            "products",
            base_slug,
            product.id,
        )

        connection.execute(
            sa.text(
                """
                UPDATE products
                SET slug = :slug
                WHERE id = :id
                """
            ),
            {
                "slug": unique_slug,
                "id": product.id,
            },
        )

    # ---------------------------------------------------------
    # Now make category slug required
    # ---------------------------------------------------------
    op.alter_column(
        "categories",
        "slug",
        existing_type=sa.String(length=120),
        nullable=False,
    )

    # ---------------------------------------------------------
    # Now make product slug required
    # ---------------------------------------------------------
    op.alter_column(
        "products",
        "slug",
        existing_type=sa.String(length=255),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "slug",
        existing_type=sa.String(length=255),
        nullable=True,
    )

    op.alter_column(
        "categories",
        "slug",
        existing_type=sa.String(length=120),
        nullable=True,
    )