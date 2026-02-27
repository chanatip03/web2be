"""update assignment relationships

Revision ID: 5e593d2edd4d
Revises: 1351c5aea6d4
Create Date: 2026-02-24 11:01:52.586409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e593d2edd4d'
down_revision: Union[str, Sequence[str], None] = '1351c5aea6d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 🔹 Seed project_types (enum style)
    op.execute("""
        INSERT INTO project_types (id, name)
        VALUES
            (1, 'FE'),
            (2, 'BE'),
            (3, 'Project')
        ON CONFLICT (id) DO NOTHING;
    """)

    # 🔹 Seed languages (JPlag supported)
    op.execute("""
        INSERT INTO languages (id, name)
        VALUES
            (1, 'Java'),
            (2, 'Python'),
            (3, 'C'),
            (4, 'C++'),
            (5, 'JavaScript'),
            (6, 'TypeScript'),
            (7, 'Go'),
            (8, 'Kotlin'),
            (9, 'Swift'),
            (10, 'Rust')
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM project_types
        WHERE id IN (1,2,3);
    """)

    op.execute("""
        DELETE FROM languages
        WHERE id IN (1,2,3,4,5,6,7,8,9,10);
    """)