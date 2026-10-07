"""add product variants

Revision ID: c4cf6c7c6a22
Revises: 178a1caa402e
Create Date: 2026-10-06 21:59:16.285508

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4cf6c7c6a22"
down_revision: Union[str, Sequence[str], None] = "178a1caa402e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "product_option_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_product_option_groups_id"),
        "product_option_groups",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_product_option_groups_product_id"),
        "product_option_groups",
        ["product_id"],
        unique=False,
    )

    op.create_table(
        "product_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("original_price", sa.Float(), nullable=True),
        sa.Column(
            "stock",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )

    op.create_index(
        op.f("ix_product_variants_id"),
        "product_variants",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_product_variants_product_id"),
        "product_variants",
        ["product_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_product_variants_sku"),
        "product_variants",
        ["sku"],
        unique=True,
    )

    op.create_table(
        "product_option_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("option_group_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=100), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.ForeignKeyConstraint(
            ["option_group_id"],
            ["product_option_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_product_option_values_id"),
        "product_option_values",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_product_option_values_option_group_id"),
        "product_option_values",
        ["option_group_id"],
        unique=False,
    )

    op.create_table(
        "product_variant_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("option_value_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["option_value_id"],
            ["product_option_values.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "variant_id",
            "option_value_id",
            name="uq_variant_option_value",
        ),
    )

    op.create_index(
        op.f("ix_product_variant_values_id"),
        "product_variant_values",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_product_variant_values_option_value_id"),
        "product_variant_values",
        ["option_value_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_product_variant_values_variant_id"),
        "product_variant_values",
        ["variant_id"],
        unique=False,
    )

    # Add variant-related fields to existing product_images table.
    op.add_column(
        "product_images",
        sa.Column(
            "variant_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "product_images",
        sa.Column(
            "view_type",
            sa.String(length=50),
            nullable=True,
        ),
    )

    op.add_column(
        "product_images",
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.alter_column(
        "product_images",
        "sort_order",
        server_default=None,
    )

    op.create_index(
        op.f("ix_product_images_variant_id"),
        "product_images",
        ["variant_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_product_images_variant_id_product_variants",
        "product_images",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint(
        "fk_product_images_variant_id_product_variants",
        "product_images",
        type_="foreignkey",
    )

    op.drop_index(
        op.f("ix_product_images_variant_id"),
        table_name="product_images",
    )

    op.drop_column(
        "product_images",
        "sort_order",
    )

    op.drop_column(
        "product_images",
        "view_type",
    )

    op.drop_column(
        "product_images",
        "variant_id",
    )

    op.drop_index(
        op.f("ix_product_variant_values_variant_id"),
        table_name="product_variant_values",
    )

    op.drop_index(
        op.f("ix_product_variant_values_option_value_id"),
        table_name="product_variant_values",
    )

    op.drop_index(
        op.f("ix_product_variant_values_id"),
        table_name="product_variant_values",
    )

    op.drop_table(
        "product_variant_values",
    )

    op.drop_index(
        op.f("ix_product_option_values_option_group_id"),
        table_name="product_option_values",
    )

    op.drop_index(
        op.f("ix_product_option_values_id"),
        table_name="product_option_values",
    )

    op.drop_table(
        "product_option_values",
    )

    op.drop_index(
        op.f("ix_product_variants_sku"),
        table_name="product_variants",
    )

    op.drop_index(
        op.f("ix_product_variants_product_id"),
        table_name="product_variants",
    )

    op.drop_index(
        op.f("ix_product_variants_id"),
        table_name="product_variants",
    )

    op.drop_table(
        "product_variants",
    )

    op.drop_index(
        op.f("ix_product_option_groups_product_id"),
        table_name="product_option_groups",
    )

    op.drop_index(
        op.f("ix_product_option_groups_id"),
        table_name="product_option_groups",
    )

    op.drop_table(
        "product_option_groups",
    )