
"""add user product viewing history

Revision ID: YOUR_GENERATED_REVISION_ID
Revises: 5cc423eba011
"""

from alembic import op
import sqlalchemy as sa


revision = "f22b2bf7c65e"
down_revision = "5cc423eba011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_product_views",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey(
                "products.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.UniqueConstraint(
            "user_id",
            "product_id",
            name="uq_user_product_views_user_product",
        ),
    )

    op.create_index(
        "ix_user_product_views_user_id",
        "user_product_views",
        ["user_id"],
    )

    op.create_index(
        "ix_user_product_views_product_id",
        "user_product_views",
        ["product_id"],
    )

    op.create_index(
        "ix_user_product_views_user_viewed",
        "user_product_views",
        ["user_id", "viewed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_product_views_user_viewed",
        table_name="user_product_views",
    )

    op.drop_index(
        "ix_user_product_views_product_id",
        table_name="user_product_views",
    )

    op.drop_index(
        "ix_user_product_views_user_id",
        table_name="user_product_views",
    )

    op.drop_table("user_product_views")
