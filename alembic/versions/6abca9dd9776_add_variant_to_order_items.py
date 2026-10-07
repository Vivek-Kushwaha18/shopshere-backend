"""add variant to order items

Revision ID: 6abca9dd9776
Revises: ba8e1e150a7f
Create Date: 2026-10-06 23:51:18.541568

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6abca9dd9776"
down_revision: Union[str, Sequence[str], None] = "ba8e1e150a7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "order_items",
        sa.Column(
            "variant_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_order_items_variant_id",
        "order_items",
        ["variant_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_order_items_variant_id_product_variants",
        "order_items",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint(
        "fk_order_items_variant_id_product_variants",
        "order_items",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_order_items_variant_id",
        table_name="order_items",
    )

    op.drop_column(
        "order_items",
        "variant_id",
    )