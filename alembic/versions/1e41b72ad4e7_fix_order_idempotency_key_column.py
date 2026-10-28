
"""fix order idempotency key column

Revision ID: 1e41b72ad4e7
Revises: 8c56afa0e1a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1e41b72ad4e7"
down_revision: Union[str, Sequence[str], None] = "8c56afa0e1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("idempotency_key", sa.String(), nullable=True),
    )

    op.create_unique_constraint(
        "uq_orders_user_id_idempotency_key",
        "orders",
        ["user_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_orders_user_id_idempotency_key",
        "orders",
        type_="unique",
    )

    op.drop_column("orders", "idempotency_key")
