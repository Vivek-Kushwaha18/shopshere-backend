
"""add signup and login security columns

Revision ID: 5cc423eba011
Revises: faa0b0122b40
Create Date: 2026-11-19 16:52:50.290504

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5cc423eba011"
down_revision: Union[str, Sequence[str], None] = "faa0b0122b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add signup OTP and login security columns."""

    op.add_column(
        "users",
        sa.Column(
            "signup_otp_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "signup_otp_window_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "login_failed_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "login_locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove signup OTP and login security columns."""

    op.drop_column(
        "users",
        "login_locked_until",
    )

    op.drop_column(
        "users",
        "login_failed_attempts",
    )

    op.drop_column(
        "users",
        "signup_otp_window_started_at",
    )

    op.drop_column(
        "users",
        "signup_otp_count",
    )
