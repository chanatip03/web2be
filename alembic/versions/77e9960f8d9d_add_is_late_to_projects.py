"""add_is_late_to_projects

Revision ID: 77e9960f8d9d
Revises: 9b3cd69b774a
Create Date: 2026-04-17 11:10:49.208673

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77e9960f8d9d'
down_revision: Union[str, Sequence[str], None] = '9b3cd69b774a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_late column to projects table (defaults to False for existing rows)
    op.add_column(
        'projects',
        sa.Column('is_late', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('projects', 'is_late')
