
"""Link order items to their source cart items.

Revision ID: c7129b3f6a21
Revises: f4129622fd67
Create Date: 2026-10-26 13:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic revision identifiers.
revision: str = "c7129b3f6a21"
down_revision: Union[str, Sequence[str], None] = "f4129622fd67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the source cart item reference to order items."""
    op.add_column(
        "order_items",
        sa.Column("cart_item_id", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_order_items_cart_item_id_cart_items",
        "order_items",
        "cart_items",
        ["cart_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_order_items_cart_item_id",
        "order_items",
        ["cart_item_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the source cart item reference."""
    op.drop_index(
        "ix_order_items_cart_item_id",
        table_name="order_items",
    )

    op.drop_constraint(
        "fk_order_items_cart_item_id_cart_items",
        "order_items",
        type_="foreignkey",
    )

    op.drop_column("order_items", "cart_item_id")
