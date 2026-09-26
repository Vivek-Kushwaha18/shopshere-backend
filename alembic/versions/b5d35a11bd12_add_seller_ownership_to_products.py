"""add seller ownership to products

Revision ID: b5d35a11bd12
Revises: ac993d84c0b9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5d35a11bd12"
down_revision: Union[str, Sequence[str], None] = "ac993d84c0b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add seller_id temporarily as nullable
    op.add_column(
        "products",
        sa.Column("seller_id", sa.Integer(), nullable=True),
    )

    # Assign existing products to seller ID 8
    op.execute(
        "UPDATE products SET seller_id = 8 WHERE seller_id IS NULL"
    )

    # Make seller_id required
    op.alter_column(
        "products",
        "seller_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Create index
    op.create_index(
        "ix_products_seller_id",
        "products",
        ["seller_id"],
        unique=False,
    )

    # products.seller_id -> users.id
    op.create_foreign_key(
        "fk_products_seller_id_users",
        "products",
        "users",
        ["seller_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_products_seller_id_users",
        "products",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_products_seller_id",
        table_name="products",
    )

    op.drop_column(
        "products",
        "seller_id",
    )