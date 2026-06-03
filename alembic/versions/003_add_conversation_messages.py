"""Add conversation_messages table for AI auto-reply context

Revision ID: 003
Revises: 002
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_phone", sa.String(50), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="messagerole"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("wamid", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wamid", name="uq_conversation_messages_wamid"),
    )
    op.create_index("ix_conversation_messages_id", "conversation_messages", ["id"])
    op.create_index(
        "ix_conversation_messages_contact_phone",
        "conversation_messages",
        ["contact_phone"],
    )
    op.create_index(
        "ix_conversation_messages_wamid",
        "conversation_messages",
        ["wamid"],
    )
    op.create_index(
        "ix_conversation_messages_created_at",
        "conversation_messages",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_created_at", "conversation_messages")
    op.drop_index("ix_conversation_messages_wamid", "conversation_messages")
    op.drop_index("ix_conversation_messages_contact_phone", "conversation_messages")
    op.drop_index("ix_conversation_messages_id", "conversation_messages")
    op.drop_table("conversation_messages")
    op.execute("DROP TYPE IF EXISTS messagerole")
