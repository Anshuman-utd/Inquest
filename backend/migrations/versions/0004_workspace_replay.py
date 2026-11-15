"""Add independent, durable workspace simulator cursors."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE operations.replay_runs ADD COLUMN workspace_id uuid
            REFERENCES operations.workspaces;
        ALTER TABLE operations.replay_runs ADD UNIQUE (workspace_id, id);
        CREATE TABLE operations.replay_jobs (
            workspace_id uuid PRIMARY KEY,
            analyst_id uuid NOT NULL,
            replay_id uuid NOT NULL,
            due_at timestamptz,
            FOREIGN KEY (workspace_id, analyst_id) REFERENCES operations.workspace_memberships,
            FOREIGN KEY (workspace_id, replay_id)
                REFERENCES operations.replay_runs (workspace_id, id)
        );
        CREATE INDEX replay_due ON operations.replay_jobs (due_at) WHERE due_at IS NOT NULL;
        GRANT SELECT, INSERT, UPDATE ON operations.replay_jobs TO inquest_api;
        GRANT INSERT, UPDATE ON operations.replay_runs TO inquest_api;
        GRANT INSERT ON operations.transaction_scores TO inquest_api;

        ALTER TABLE operations.replay_runs ENABLE ROW LEVEL SECURITY;
        CREATE POLICY replay_read ON operations.replay_runs FOR SELECT TO inquest_api USING (
            workspace_id IS NULL
            OR workspace_id = nullif(current_setting('inquest.workspace_id', true), '')::uuid
        );
        CREATE POLICY replay_insert ON operations.replay_runs FOR INSERT TO inquest_api WITH CHECK (
            workspace_id = nullif(current_setting('inquest.workspace_id', true), '')::uuid
        );
        CREATE POLICY replay_update ON operations.replay_runs FOR UPDATE TO inquest_api
            USING (workspace_id = nullif(current_setting('inquest.workspace_id', true), '')::uuid)
            WITH CHECK (
                workspace_id = nullif(current_setting('inquest.workspace_id', true), '')::uuid
            );

        ALTER TABLE operations.transaction_scores ENABLE ROW LEVEL SECURITY;
        CREATE POLICY score_read ON operations.transaction_scores FOR SELECT TO inquest_api
            USING (EXISTS (
                SELECT 1 FROM operations.replay_runs r WHERE r.id = replay_id
            ));
        CREATE POLICY score_insert ON operations.transaction_scores FOR INSERT TO inquest_api
            WITH CHECK (EXISTS (
                SELECT 1 FROM operations.replay_runs r WHERE r.id = replay_id
                    AND r.workspace_id =
                        nullif(current_setting('inquest.workspace_id', true), '')::uuid
            ));
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY score_insert ON operations.transaction_scores;
        DROP POLICY score_read ON operations.transaction_scores;
        ALTER TABLE operations.transaction_scores DISABLE ROW LEVEL SECURITY;
        DROP POLICY replay_insert ON operations.replay_runs;
        DROP POLICY replay_update ON operations.replay_runs;
        DROP POLICY replay_read ON operations.replay_runs;
        ALTER TABLE operations.replay_runs DISABLE ROW LEVEL SECURITY;
        DROP TABLE operations.replay_jobs;
        ALTER TABLE operations.replay_runs DROP COLUMN workspace_id;
        REVOKE INSERT, UPDATE ON operations.replay_runs FROM inquest_api;
        REVOKE INSERT ON operations.transaction_scores FROM inquest_api;
    """)
