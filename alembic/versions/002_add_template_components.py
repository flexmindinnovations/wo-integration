"""Add template_language and template_components to campaigns

Revision ID: 002
Revises: 001
Create Date: 2026-06-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("template_language", sa.String(10), nullable=True))
    op.add_column("campaigns", sa.Column("template_components", sa.JSON(), nullable=True))

    # Default existing rows to language "en"
    op.execute("UPDATE campaigns SET template_language = 'en' WHERE template_language IS NULL")


def downgrade() -> None:
    op.drop_column("campaigns", "template_components")
    op.drop_column("campaigns", "template_language")
