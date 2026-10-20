"""create AI conversations and messages

Revision ID: 0dbbac32474d
Revises: 6abca9dd9776
Create Date: 2026-10-20 09:25:53.434407

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers used by Alembic.
revision: str = "0dbbac32474d"
down_revision: Union[str, Sequence[str], None] = "6abca9dd9776"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create AI conversation and message tables."""

    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_ai_conversations_id"),
        "ai_conversations",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_ai_conversations_user_id"),
        "ai_conversations",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_ai_messages_conversation_id"),
        "ai_messages",
        ["conversation_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_ai_messages_id"),
        "ai_messages",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the AI conversation and message tables."""

    op.drop_index(
        op.f("ix_ai_messages_id"),
        table_name="ai_messages",
    )

    op.drop_index(
        op.f("ix_ai_messages_conversation_id"),
        table_name="ai_messages",
    )

    op.drop_table("ai_messages")

    op.drop_index(
        op.f("ix_ai_conversations_user_id"),
        table_name="ai_conversations",
    )

    op.drop_index(
        op.f("ix_ai_conversations_id"),
        table_name="ai_conversations",
    )

    op.drop_table("ai_conversations")
