"""add is_active to categories

Revision ID: 6483e3a86b56
Revises: d34e90475e1f
Create Date: 2026-09-26 17:16:03.617969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6483e3a86b56'
down_revision: Union[str, Sequence[str], None] = 'd34e90475e1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
