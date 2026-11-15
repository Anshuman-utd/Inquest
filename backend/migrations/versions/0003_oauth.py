"""Persist OAuth identities, browser authorization attempts, and revocable sessions."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE operations.oauth_attempts (
            state_hash text PRIMARY KEY,
            provider text NOT NULL CHECK (provider IN ('github', 'google')),
            verifier text NOT NULL,
            nonce text NOT NULL,
            return_to text NOT NULL CHECK (return_to IN ('/login', '/signup')),
            expires_at timestamptz NOT NULL DEFAULT now() + interval '10 minutes'
        );
        CREATE INDEX oauth_attempt_expiry ON operations.oauth_attempts (expires_at);
        CREATE INDEX analyst_session_expiry ON operations.analyst_sessions (expires_at);
        CREATE TABLE operations.oauth_identities (
            provider text NOT NULL CHECK (provider IN ('github', 'google')),
            subject text NOT NULL,
            workspace_id uuid NOT NULL,
            analyst_id uuid NOT NULL,
            PRIMARY KEY (provider, subject),
            FOREIGN KEY (workspace_id, analyst_id) REFERENCES operations.workspace_memberships
        );
        INSERT INTO operations.oauth_identities
        SELECT DISTINCT ON (a.github_subject)
            'github', a.github_subject, m.workspace_id, a.id
        FROM operations.analysts a
        JOIN operations.workspace_memberships m ON m.analyst_id = a.id
        WHERE a.github_subject ~ '^[1-9][0-9]*$'
        ORDER BY a.github_subject, m.workspace_id;
        ALTER TABLE operations.analysts ALTER COLUMN github_subject DROP NOT NULL;
        GRANT SELECT, INSERT, DELETE ON operations.oauth_attempts TO inquest_api;
        GRANT INSERT, DELETE ON operations.analyst_sessions TO inquest_api;

        CREATE FUNCTION operations.provision_oauth(_provider text, _subject text)
        RETURNS TABLE (workspace_id uuid, analyst_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog, pg_temp AS $$
        DECLARE
            workspace uuid;
            analyst uuid;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(_provider || ':' || _subject, 3483));
            SELECT i.workspace_id, i.analyst_id INTO workspace, analyst
            FROM operations.oauth_identities i
            WHERE i.provider = _provider AND i.subject = _subject;
            IF NOT FOUND THEN
                INSERT INTO operations.workspaces DEFAULT VALUES RETURNING id INTO workspace;
                INSERT INTO operations.analysts DEFAULT VALUES RETURNING id INTO analyst;
                INSERT INTO operations.workspace_memberships VALUES (workspace, analyst);
                INSERT INTO operations.oauth_identities VALUES (
                    _provider, _subject, workspace, analyst
                );
            END IF;
            RETURN QUERY SELECT workspace, analyst;
        END
        $$;
        REVOKE ALL ON FUNCTION operations.provision_oauth(text, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION operations.provision_oauth(text, text) TO inquest_api;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION operations.provision_oauth(text, text);
        DROP TABLE operations.oauth_identities, operations.oauth_attempts;
        DROP INDEX operations.analyst_session_expiry;
        REVOKE INSERT, DELETE ON operations.analyst_sessions FROM inquest_api;
        UPDATE operations.analysts
        SET github_subject = 'oauth-' || id::text WHERE github_subject IS NULL;
        ALTER TABLE operations.analysts ALTER COLUMN github_subject SET NOT NULL;
    """)
