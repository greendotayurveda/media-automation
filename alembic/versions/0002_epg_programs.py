"""Add epg_programs table for Live TV guide.

Revision ID: 0002_epg_programs
Revises: 0001_initial_schema
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op

from shared.database.base import Base
import shared.database.models  # noqa: F401

revision: str = "0002_epg_programs"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # create_all is idempotent for existing tables; creates epg_programs
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    op.drop_table("epg_programs")
