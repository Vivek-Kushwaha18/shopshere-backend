"""add order idempotency key

Revision ID: 8c56afa0e1a7
Revises: 6cb350a2c5f5
Create Date: 2026-10-28 11:10:05.456863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c56afa0e1a7'
down_revision: Union[str, Sequence[str], None] = '6cb350a2c5f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
