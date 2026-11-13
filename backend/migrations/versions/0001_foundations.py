"""Create shared synthetic data and workspace-scoped investigation tables."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "workspace_memberships",
    "cases",
    "investigations",
    "tool_calls",
    "investigation_events",
    "decisions",
    "notes",
    "workspace_usage",
)


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA fixture;
        CREATE SCHEMA operations;
        CREATE SCHEMA evaluation;

        CREATE TABLE fixture.datasets (
            id text PRIMARY KEY,
            seed bigint NOT NULL,
            manifest jsonb NOT NULL
        );
        CREATE TABLE fixture.cities (
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            id text NOT NULL,
            name text NOT NULL,
            latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
            longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
            PRIMARY KEY (dataset_id, id)
        );
        CREATE TABLE fixture.customers (
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            id text NOT NULL,
            alias text NOT NULL,
            home_city_id text NOT NULL,
            PRIMARY KEY (dataset_id, id),
            FOREIGN KEY (dataset_id, home_city_id) REFERENCES fixture.cities
        );
        CREATE TABLE fixture.merchants (
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            id text NOT NULL,
            alias text NOT NULL,
            category text NOT NULL,
            city_id text NOT NULL,
            risk_tier text NOT NULL CHECK (risk_tier IN ('standard', 'elevated')),
            PRIMARY KEY (dataset_id, id),
            FOREIGN KEY (dataset_id, city_id) REFERENCES fixture.cities
        );
        CREATE TABLE fixture.devices (
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            id text NOT NULL,
            PRIMARY KEY (dataset_id, id)
        );
        CREATE TABLE fixture.transactions (
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            source_sequence bigint NOT NULL CHECK (source_sequence > 0),
            customer_id text NOT NULL,
            merchant_id text NOT NULL,
            device_id text NOT NULL,
            instrument_id text NOT NULL,
            city_id text,
            location_source text NOT NULL CHECK (location_source IN ('physical', 'remote')),
            occurred_at timestamptz NOT NULL,
            amount_minor bigint NOT NULL CHECK (amount_minor > 0),
            currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            channel text NOT NULL CHECK (channel IN ('card', 'upi')),
            flow text NOT NULL CHECK (flow IN ('purchase', 'push', 'collect')),
            declined boolean NOT NULL,
            recent_reregistration boolean NOT NULL,
            PRIMARY KEY (dataset_id, source_sequence),
            FOREIGN KEY (dataset_id, customer_id) REFERENCES fixture.customers,
            FOREIGN KEY (dataset_id, merchant_id) REFERENCES fixture.merchants,
            FOREIGN KEY (dataset_id, device_id) REFERENCES fixture.devices,
            FOREIGN KEY (dataset_id, city_id) REFERENCES fixture.cities,
            CHECK ((channel = 'card') = (flow = 'purchase')),
            CHECK ((city_id IS NOT NULL) = (location_source = 'physical'))
        );
        CREATE INDEX transactions_customer_time
            ON fixture.transactions (dataset_id, customer_id, occurred_at, source_sequence);
        CREATE INDEX transactions_merchant_time
            ON fixture.transactions (dataset_id, merchant_id, occurred_at, source_sequence);
        CREATE INDEX transactions_device_time
            ON fixture.transactions (dataset_id, device_id, occurred_at, source_sequence);

        CREATE TABLE evaluation.truth (
            dataset_id text NOT NULL,
            source_sequence bigint NOT NULL,
            is_fraud boolean NOT NULL,
            scenario text,
            episode_id text,
            PRIMARY KEY (dataset_id, source_sequence),
            FOREIGN KEY (dataset_id, source_sequence) REFERENCES fixture.transactions,
            CHECK ((scenario IS NULL) = (episode_id IS NULL)),
            CHECK (NOT is_fraud OR scenario IS NOT NULL)
        );
        CREATE TABLE evaluation.eval_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            configuration jsonb NOT NULL,
            metrics jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, dataset_id)
        );
        CREATE TABLE evaluation.eval_case_results (
            eval_run_id uuid NOT NULL,
            dataset_id text NOT NULL,
            source_sequence bigint NOT NULL,
            result jsonb NOT NULL,
            PRIMARY KEY (eval_run_id, source_sequence),
            FOREIGN KEY (eval_run_id, dataset_id) REFERENCES evaluation.eval_runs (id, dataset_id),
            FOREIGN KEY (dataset_id, source_sequence) REFERENCES evaluation.truth
        );

        CREATE TABLE operations.workspaces (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid()
        );
        CREATE TABLE operations.analysts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            github_subject text NOT NULL UNIQUE
        );
        CREATE TABLE operations.workspace_memberships (
            workspace_id uuid NOT NULL REFERENCES operations.workspaces,
            analyst_id uuid NOT NULL REFERENCES operations.analysts,
            PRIMARY KEY (workspace_id, analyst_id)
        );
        CREATE TABLE operations.replay_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_id text NOT NULL REFERENCES fixture.datasets,
            cursor bigint NOT NULL DEFAULT 0 CHECK (cursor >= 0),
            state text NOT NULL DEFAULT 'paused' CHECK (state IN ('paused', 'running', 'complete')),
            UNIQUE (id, dataset_id)
        );
        CREATE TABLE operations.transaction_scores (
            replay_id uuid NOT NULL,
            dataset_id text NOT NULL,
            source_sequence bigint NOT NULL,
            model_version text NOT NULL,
            feature_version text NOT NULL,
            score double precision NOT NULL CHECK (score BETWEEN 0 AND 1),
            threshold double precision NOT NULL CHECK (threshold BETWEEN 0 AND 1),
            contributions jsonb NOT NULL,
            PRIMARY KEY (replay_id, dataset_id, source_sequence, model_version),
            FOREIGN KEY (replay_id, dataset_id) REFERENCES operations.replay_runs (id, dataset_id),
            FOREIGN KEY (dataset_id, source_sequence) REFERENCES fixture.transactions
        );
        CREATE TABLE operations.cases (
            workspace_id uuid NOT NULL REFERENCES operations.workspaces,
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            replay_id uuid NOT NULL,
            dataset_id text NOT NULL,
            source_sequence bigint NOT NULL,
            model_version text NOT NULL,
            status text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'investigating', 'review', 'resolved', 'escalated')),
            version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            UNIQUE (workspace_id, replay_id, dataset_id, source_sequence),
            FOREIGN KEY (replay_id, dataset_id, source_sequence, model_version)
                REFERENCES operations.transaction_scores
        );
        CREATE INDEX cases_queue ON operations.cases (workspace_id, status, created_at, id);
        CREATE TABLE operations.investigations (
            workspace_id uuid NOT NULL,
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'review', 'resume', 'complete', 'failed')),
            mode text NOT NULL CHECK (mode IN ('live', 'replay')),
            lease_until timestamptz,
            configuration jsonb NOT NULL DEFAULT '{}',
            report jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            UNIQUE (id),
            UNIQUE (workspace_id, case_id, id),
            FOREIGN KEY (workspace_id, case_id) REFERENCES operations.cases
        );
        CREATE UNIQUE INDEX investigations_active
            ON operations.investigations (workspace_id, case_id)
            WHERE status IN ('queued', 'running', 'review', 'resume');
        CREATE TABLE operations.tool_calls (
            workspace_id uuid NOT NULL,
            investigation_id uuid NOT NULL,
            sequence integer NOT NULL CHECK (sequence > 0),
            evidence_id text NOT NULL,
            tool_name text NOT NULL,
            inputs jsonb NOT NULL,
            observation jsonb NOT NULL,
            PRIMARY KEY (workspace_id, investigation_id, sequence),
            UNIQUE (workspace_id, evidence_id),
            FOREIGN KEY (workspace_id, investigation_id) REFERENCES operations.investigations
        );
        CREATE TABLE operations.investigation_events (
            workspace_id uuid NOT NULL,
            investigation_id uuid NOT NULL,
            sequence bigint NOT NULL CHECK (sequence > 0),
            deduplication_key text NOT NULL,
            kind text NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, investigation_id, sequence),
            UNIQUE (workspace_id, investigation_id, deduplication_key),
            FOREIGN KEY (workspace_id, investigation_id) REFERENCES operations.investigations
        );
        CREATE TABLE operations.decisions (
            workspace_id uuid NOT NULL,
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL,
            investigation_id uuid NOT NULL,
            analyst_id uuid NOT NULL,
            operation text NOT NULL CHECK (operation IN ('approve', 'override', 'escalate')),
            disposition text NOT NULL CHECK (disposition IN ('block', 'release', 'escalate')),
            prior_case_version integer NOT NULL CHECK (prior_case_version >= 0),
            idempotency_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            UNIQUE (workspace_id, investigation_id),
            UNIQUE (workspace_id, idempotency_key),
            FOREIGN KEY (workspace_id, case_id, investigation_id)
                REFERENCES operations.investigations (workspace_id, case_id, id),
            FOREIGN KEY (workspace_id, analyst_id) REFERENCES operations.workspace_memberships
        );
        CREATE TABLE operations.notes (
            workspace_id uuid NOT NULL,
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL,
            analyst_id uuid NOT NULL,
            body text NOT NULL CHECK (char_length(trim(body)) BETWEEN 1 AND 1000),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            FOREIGN KEY (workspace_id, case_id) REFERENCES operations.cases,
            FOREIGN KEY (workspace_id, analyst_id) REFERENCES operations.workspace_memberships
        );
        CREATE TABLE operations.workspace_usage (
            workspace_id uuid NOT NULL REFERENCES operations.workspaces,
            utc_day date NOT NULL,
            live_starts integer NOT NULL CHECK (live_starts >= 0),
            PRIMARY KEY (workspace_id, utc_day)
        );
        CREATE TABLE operations.global_usage (
            utc_day date PRIMARY KEY,
            reserved_tokens bigint NOT NULL CHECK (reserved_tokens >= 0)
        );
        CREATE TABLE operations.runtime_controls (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            llm_enabled boolean NOT NULL DEFAULT false
        );
        INSERT INTO operations.runtime_controls DEFAULT VALUES;
        CREATE TABLE operations.ip_rate_limits (
            action text NOT NULL CHECK (action IN ('signup', 'investigate')),
            ip_hash text NOT NULL,
            window_started_at timestamptz NOT NULL,
            attempts integer NOT NULL CHECK (attempts > 0),
            PRIMARY KEY (action, ip_hash, window_started_at)
        );

        GRANT USAGE ON SCHEMA fixture TO inquest_api, inquest_tool, inquest_eval;
        GRANT SELECT ON ALL TABLES IN SCHEMA fixture TO inquest_api, inquest_tool, inquest_eval;
        GRANT USAGE ON SCHEMA evaluation TO inquest_eval;
        GRANT SELECT ON evaluation.truth TO inquest_eval;
        GRANT SELECT, INSERT, UPDATE ON evaluation.eval_runs, evaluation.eval_case_results
            TO inquest_eval;
        GRANT USAGE ON SCHEMA operations TO inquest_api;
        GRANT SELECT ON operations.replay_runs, operations.transaction_scores,
            operations.workspace_memberships, operations.runtime_controls TO inquest_api;
        GRANT SELECT, INSERT, UPDATE ON operations.cases, operations.investigations,
            operations.workspace_usage, operations.global_usage, operations.ip_rate_limits
            TO inquest_api;
        GRANT SELECT, INSERT ON operations.tool_calls, operations.investigation_events,
            operations.decisions, operations.notes TO inquest_api;
    """)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY workspace_scope ON operations.{table} TO inquest_api
                USING (
                    workspace_id = nullif(current_setting('inquest.workspace_id', true), '')::uuid
                )
                WITH CHECK (
                    workspace_id = nullif(current_setting('inquest.workspace_id', true), '')::uuid
                )
        """)


def downgrade() -> None:
    op.execute("""
        DROP SCHEMA operations CASCADE;
        DROP SCHEMA evaluation CASCADE;
        DROP SCHEMA fixture CASCADE;
    """)
