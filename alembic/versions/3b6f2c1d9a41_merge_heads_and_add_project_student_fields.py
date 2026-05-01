"""merge heads and add project student fields

Revision ID: 3b6f2c1d9a41
Revises: 77e9960f8d9d, e1bce97de807
Create Date: 2026-04-21

This migration resolves the accidental two-head situation and ensures
the `projects` table contains columns expected by the ORM/submission flow.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b6f2c1d9a41"
down_revision: Union[str, Sequence[str], None] = ("77e9960f8d9d", "e1bce97de807")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add missing columns safely (Postgres supports IF NOT EXISTS).
    op.execute('ALTER TABLE projects ADD COLUMN IF NOT EXISTS student_id INTEGER')
    op.execute('ALTER TABLE projects ADD COLUMN IF NOT EXISTS container_id VARCHAR')
    op.execute('ALTER TABLE projects ADD COLUMN IF NOT EXISTS container_resource VARCHAR')

    # Add FK constraint safely.
    op.execute(
        """
        DO $$
        BEGIN
          ALTER TABLE projects
            ADD CONSTRAINT projects_student_id_fkey
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE;
        EXCEPTION
          WHEN duplicate_object THEN
            NULL;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Best-effort downgrade; keep it safe if objects don't exist.
    op.execute(
        """
        DO $$
        BEGIN
          ALTER TABLE projects DROP CONSTRAINT projects_student_id_fkey;
        EXCEPTION
          WHEN undefined_object THEN
            NULL;
        END
        $$;
        """
    )
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS container_resource")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS container_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS student_id")

