
"""add icon_url to categories

Revision ID: faa0b0122b40
Revises: 1e41b72ad4e7
Create Date: 2026-11-19 13:39:26.133986

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "faa0b0122b40"

down_revision: Union[str, Sequence[str], None] = (
    "1e41b72ad4e7"
)

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade() -> None:
    """Add icon_url column to categories."""

    op.add_column(
        "categories",
        sa.Column(
            "icon_url",
            sa.String(length=1000),
            nullable=True,
        ),
    )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade() -> None:
    """Remove icon_url column from categories."""

    op.drop_column(
        "categories",
        "icon_url",
    )
