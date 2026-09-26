from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "9d8914e378cf"
down_revision: Union[str, Sequence[str], None] = "713a9e3c82f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    # Add rating if it does not exist.
    if "rating" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "rating",
                sa.Float(),
                nullable=True,
                server_default="0",
            ),
        )

    # Add reviews_count if it does not exist.
    # This prevents the next migration error if production is also missing it.
    if "reviews_count" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "reviews_count",
                sa.Integer(),
                nullable=True,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    product_columns = {
        column["name"]
        for column in inspector.get_columns("products")
    }

    if "reviews_count" in product_columns:
        op.drop_column(
            "products",
            "reviews_count",
        )

    if "rating" in product_columns:
        op.drop_column(
            "products",
            "rating",
        )