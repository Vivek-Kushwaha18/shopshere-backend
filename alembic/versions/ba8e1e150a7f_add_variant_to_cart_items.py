"""add variant to cart items

Revision ID: ba8e1e150a7f
Revises: c4cf6c7c6a22
Create Date: 2026-10-06 23:34:31.479142

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ba8e1e150a7f"
down_revision: Union[str, Sequence[str], None] = "c4cf6c7c6a22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ---------------------------------------------------------
    # Add variant_id to cart_items
    # ---------------------------------------------------------

    op.add_column(
        "cart_items",
        sa.Column(
            "variant_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    # ---------------------------------------------------------
    # Remove old unique constraint
    # ---------------------------------------------------------
    # The old constraint allowed only one cart item for a
    # product, which does not work when the same product has
    # multiple variants.

    op.drop_constraint(
        "uq_cart_item_cart_product",
        "cart_items",
        type_="unique",
    )

    # ---------------------------------------------------------
    # Index for variant_id
    # ---------------------------------------------------------

    op.create_index(
        "ix_cart_items_variant_id",
        "cart_items",
        ["variant_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # Foreign key
    # ---------------------------------------------------------

    op.create_foreign_key(
        "fk_cart_items_variant_id_product_variants",
        "cart_items",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ---------------------------------------------------------
    # Unique index for products WITHOUT variants
    # ---------------------------------------------------------
    #
    # Example:
    #
    # cart_id = 1
    # product_id = 20
    # variant_id = NULL
    #
    # Only one such item is allowed in a cart.

    op.create_index(
        "uq_cart_item_cart_product_no_variant",
        "cart_items",
        ["cart_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(
            "variant_id IS NULL"
        ),
    )

    # ---------------------------------------------------------
    # Unique index for products WITH variants
    # ---------------------------------------------------------
    #
    # Example:
    #
    # cart_id = 1
    # product_id = 38
    # variant_id = 1
    #
    # The same variant cannot appear twice.
    #
    # But:
    #
    # variant_id = 1
    # variant_id = 2
    #
    # can both exist because they are different variants.

    op.create_index(
        "uq_cart_item_cart_product_variant",
        "cart_items",
        [
            "cart_id",
            "product_id",
            "variant_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "variant_id IS NOT NULL"
        ),
    )

    # ---------------------------------------------------------
    # IMPORTANT
    # ---------------------------------------------------------
    # Do NOT remove product_variants.sku unique constraint.
    #
    # Alembic incorrectly detected it as removed because of
    # the current model/database metadata difference.
    #
    # It is intentionally preserved.


def downgrade() -> None:
    """Downgrade schema."""

    # ---------------------------------------------------------
    # Remove variant-specific unique index
    # ---------------------------------------------------------

    op.drop_index(
        "uq_cart_item_cart_product_variant",
        table_name="cart_items",
    )

    # ---------------------------------------------------------
    # Remove non-variant unique index
    # ---------------------------------------------------------

    op.drop_index(
        "uq_cart_item_cart_product_no_variant",
        table_name="cart_items",
    )

    # ---------------------------------------------------------
    # Remove foreign key
    # ---------------------------------------------------------

    op.drop_constraint(
        "fk_cart_items_variant_id_product_variants",
        "cart_items",
        type_="foreignkey",
    )

    # ---------------------------------------------------------
    # Remove variant_id index
    # ---------------------------------------------------------

    op.drop_index(
        "ix_cart_items_variant_id",
        table_name="cart_items",
    )

    # ---------------------------------------------------------
    # Restore old unique constraint
    # ---------------------------------------------------------

    op.create_unique_constraint(
        "uq_cart_item_cart_product",
        "cart_items",
        [
            "cart_id",
            "product_id",
        ],
    )

    # ---------------------------------------------------------
    # Remove variant_id
    # ---------------------------------------------------------

    op.drop_column(
        "cart_items",
        "variant_id",
    )