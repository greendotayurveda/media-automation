"""Alter downloads external_id and title columns to TEXT.

Revision ID: 0003_alter_downloads_external_id_text
Revises: 0002_epg_programs
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_alter_downloads_external_id_text"
down_revision: Union[str, None] = "0002_epg_programs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("downloads", "external_id", type_=sa.Text(), existing_type=sa.String(255), nullable=True)
    op.alter_column("downloads", "title", type_=sa.Text(), existing_type=sa.String(500), nullable=False)


def downgrade() -> None:
    op.alter_column("downloads", "external_id", type_=sa.String(255), existing_type=sa.Text(), nullable=True)
    op.alter_column("downloads", "title", type_=sa.String(500), existing_type=sa.Text(), nullable=False)
