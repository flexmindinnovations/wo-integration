"""Initial schema — contacts, campaigns, campaign_messages

Revision ID: 001
Revises:
Create Date: 2026-06-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("odoo_partner_id", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone"),
        sa.UniqueConstraint("odoo_partner_id", name="uq_contacts_odoo_partner_id"),
    )
    op.create_index("ix_contacts_id", "contacts", ["id"])
    op.create_index("ix_contacts_phone", "contacts", ["phone"])
    op.create_index("ix_contacts_odoo_partner_id", "contacts", ["odoo_partner_id"])

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("template_name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "scheduled", "running", "completed", "failed", name="campaignstatus"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_id", "campaigns", ["id"])

    op.create_table(
        "campaign_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("whatsapp_message_id", sa.String(255), nullable=True),
        sa.Column(
            "delivery_status",
            sa.Enum("pending", "sent", "delivered", "read", "failed", name="deliverystatus"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_messages_id", "campaign_messages", ["id"])
    op.create_index("ix_campaign_messages_campaign_id", "campaign_messages", ["campaign_id"])
    op.create_index("ix_campaign_messages_contact_id", "campaign_messages", ["contact_id"])
    op.create_index(
        "ix_campaign_messages_whatsapp_message_id",
        "campaign_messages",
        ["whatsapp_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_messages_whatsapp_message_id", "campaign_messages")
    op.drop_index("ix_campaign_messages_contact_id", "campaign_messages")
    op.drop_index("ix_campaign_messages_campaign_id", "campaign_messages")
    op.drop_index("ix_campaign_messages_id", "campaign_messages")
    op.drop_table("campaign_messages")

    op.drop_index("ix_campaigns_id", "campaigns")
    op.drop_table("campaigns")

    op.drop_index("ix_contacts_odoo_partner_id", "contacts")
    op.drop_index("ix_contacts_phone", "contacts")
    op.drop_index("ix_contacts_id", "contacts")
    op.drop_table("contacts")

    op.execute("DROP TYPE IF EXISTS campaignstatus")
    op.execute("DROP TYPE IF EXISTS deliverystatus")
