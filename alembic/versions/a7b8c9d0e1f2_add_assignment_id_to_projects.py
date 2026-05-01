"""add assignment_id to projects

Revision ID: a7b8c9d0e1f2
Revises: 3b6f2c1d9a41
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = '3b6f2c1d9a41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add assignment_id column safely
    op.execute('ALTER TABLE projects ADD COLUMN IF NOT EXISTS assignment_id INTEGER')
    
    # Add FK constraint safely
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'projects_assignment_id_fkey'
          ) THEN
            ALTER TABLE projects
              ADD CONSTRAINT projects_assignment_id_fkey
              FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute('ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_assignment_id_fkey')
    op.execute('ALTER TABLE projects DROP COLUMN IF EXISTS assignment_id')
