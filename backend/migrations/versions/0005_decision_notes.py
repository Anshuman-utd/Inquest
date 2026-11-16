"""Associate each note written during a decision with its decision record."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE operations.notes ADD COLUMN decision_id uuid;
        ALTER TABLE operations.notes
            ADD FOREIGN KEY (workspace_id, decision_id) REFERENCES operations.decisions;
        ALTER TABLE operations.notes ADD UNIQUE (workspace_id, decision_id);
        WITH candidates AS (
            SELECT n.workspace_id, n.id AS note_id, d.id AS decision_id,
                   count(*) OVER (PARTITION BY n.workspace_id, n.id) AS matches,
                   count(*) OVER (PARTITION BY d.workspace_id, d.id) AS notes
            FROM operations.notes n JOIN operations.decisions d
                ON (n.workspace_id, n.case_id, n.analyst_id, n.created_at)
                 = (d.workspace_id, d.case_id, d.analyst_id, d.created_at)
        )
        UPDATE operations.notes n SET decision_id = c.decision_id
        FROM candidates c
        WHERE (n.workspace_id, n.id) = (c.workspace_id, c.note_id)
            AND c.matches = 1 AND c.notes = 1;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE operations.notes DROP COLUMN decision_id")
