"""Add durable investigation work, bearer sessions, and budget accounting."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA agent_checkpoints;
        GRANT USAGE ON SCHEMA agent_checkpoints TO inquest_api;

        ALTER TABLE operations.investigations
            ADD COLUMN started_at timestamptz,
            ADD COLUMN used_tokens integer NOT NULL DEFAULT 0 CHECK (used_tokens >= 0),
            ADD COLUMN start_key text;
        CREATE UNIQUE INDEX investigation_start_key
            ON operations.investigations (workspace_id, start_key);
        ALTER TABLE operations.decisions ADD COLUMN request_payload jsonb;
        CREATE TABLE operations.agent_jobs (
            workspace_id uuid NOT NULL,
            investigation_id uuid PRIMARY KEY,
            analyst_id uuid NOT NULL,
            queued_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (workspace_id, investigation_id) REFERENCES operations.investigations,
            FOREIGN KEY (workspace_id, analyst_id) REFERENCES operations.workspace_memberships
        );
        CREATE TABLE operations.analyst_sessions (
            token_sha256 text PRIMARY KEY,
            workspace_id uuid NOT NULL,
            analyst_id uuid NOT NULL,
            expires_at timestamptz NOT NULL,
            FOREIGN KEY (workspace_id, analyst_id) REFERENCES operations.workspace_memberships
        );
        GRANT SELECT, INSERT, DELETE ON operations.agent_jobs TO inquest_api;
        GRANT SELECT ON operations.analyst_sessions TO inquest_api;
        GRANT DELETE ON operations.ip_rate_limits TO inquest_api;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE operations.decisions DROP COLUMN request_payload;
        DROP TABLE operations.analyst_sessions, operations.agent_jobs;
        REVOKE DELETE ON operations.ip_rate_limits FROM inquest_api;
        DROP INDEX operations.investigation_start_key;
        ALTER TABLE operations.investigations
            DROP COLUMN started_at, DROP COLUMN used_tokens, DROP COLUMN start_key;
        DROP SCHEMA agent_checkpoints CASCADE;
    """)
