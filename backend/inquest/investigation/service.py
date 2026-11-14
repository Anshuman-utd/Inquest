import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from langgraph.types import Command
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError

from inquest.db.tenant import TenantDatabase, WorkspaceAccessDenied
from inquest.investigation.checkpoints import checkpoint_connection
from inquest.investigation.contracts import ToolScope
from inquest.investigation.graph import Steps, build_graph
from inquest.investigation.reports import Report
from inquest.investigation.repository import InvestigationUnavailable
from inquest.investigation.runtime import (
    Conflict,
    DecisionRequest,
    consume_ip,
    disposition,
    event,
    locked_run,
    take_live_slot,
)
from inquest.settings import Settings

log = logging.getLogger(__name__)
WORKER_LOCK = 63812744


class Investigations:
    def __init__(self, engine: Engine, steps: Steps, settings: Settings) -> None:
        self.engine = engine
        self.steps = steps
        self.settings = settings
        self.tenants = TenantDatabase(engine)

    @contextmanager
    def scoped(self, scope: ToolScope) -> Iterator[Connection]:
        with self.tenants.transaction(
            workspace_id=scope.workspace_id, analyst_id=scope.analyst_id
        ) as connection:
            yield connection

    def auth(self, token_hash: str) -> tuple[UUID, UUID] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("""
                SELECT workspace_id, analyst_id FROM operations.analyst_sessions
                WHERE token_sha256 = :hash AND expires_at > now()
            """),
                {"hash": token_hash},
            ).one_or_none()
        return (row.workspace_id, row.analyst_id) if row else None

    def start(self, scope: ToolScope, case_id: UUID, key: str, ip_hash: str) -> UUID:
        with self.scoped(scope) as connection:
            consume_ip(connection, ip_hash, self.settings.investigate_per_ip_minute)
        with self.scoped(scope) as connection:
            # Serialize starts in the workspace, including reuse of a key on another case.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:workspace))"),
                {"workspace": str(scope.workspace_id)},
            )
            existing = connection.execute(
                text("""
                SELECT id, case_id FROM operations.investigations WHERE start_key = :key
            """),
                {"key": key},
            ).one_or_none()
            if existing is not None:
                if existing.case_id != case_id:
                    raise Conflict("idempotency key belongs to another case")
                return UUID(str(existing.id))
            row = connection.execute(
                text("""
                SELECT c.status FROM operations.cases AS c JOIN operations.replay_runs AS r
                    ON (c.replay_id, c.dataset_id) = (r.id, r.dataset_id)
                WHERE c.id = :case AND c.source_sequence <= r.cursor FOR UPDATE OF c
            """),
                {"case": case_id},
            ).one_or_none()
            if row is None:
                raise InvestigationUnavailable
            if row.status != "queued":
                raise Conflict("case is not queued")
            live = self.steps.gateway is not None and take_live_slot(
                connection, scope.workspace_id, self.settings.workspace_daily_investigations
            )
            connection.execute(
                text("""
                INSERT INTO operations.investigations
                    (workspace_id, id, case_id, mode, start_key)
                VALUES (:workspace, :id, :case, :mode, :key)
            """),
                {
                    "workspace": scope.workspace_id,
                    "id": scope.investigation_id,
                    "case": case_id,
                    "mode": "live" if live else "replay",
                    "key": key,
                },
            )
            connection.execute(
                text("""
                UPDATE operations.cases SET status = 'investigating', version = version + 1
                WHERE id = :case
            """),
                {"case": case_id},
            )
            self.enqueue(connection, scope)
            event(connection, scope, "queued", "queued", {"mode": "live" if live else "replay"})
            return scope.investigation_id

    def decide(self, scope: ToolScope, request: DecisionRequest, key: str) -> UUID:
        fingerprint = {"sha256": sha256(request.model_dump_json().encode()).hexdigest()}
        with self.scoped(scope) as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:workspace))"),
                {"workspace": str(scope.workspace_id)},
            )
            run = locked_run(connection, scope)
            prior = connection.execute(
                text("""
                SELECT id, idempotency_key, analyst_id, operation, disposition, prior_case_version,
                    investigation_id, request_payload
                FROM operations.decisions WHERE investigation_id = :id OR idempotency_key = :key
            """),
                {"id": scope.investigation_id, "key": key},
            ).all()
            if prior:
                previous = prior[0]
                if (
                    len(prior) == 1
                    and previous.idempotency_key == key
                    and previous.analyst_id == scope.analyst_id
                    and previous.request_payload == fingerprint
                    and previous.investigation_id == scope.investigation_id
                ):
                    return UUID(str(previous.id))
                raise Conflict("decision already exists or key was reused")
            if run.status != "review":
                raise Conflict("investigation is not awaiting review")
            version = connection.execute(
                text("""
                SELECT version FROM operations.cases WHERE id = :case FOR UPDATE
            """),
                {"case": run.case_id},
            ).scalar_one()
            if version != request.expected_case_version:
                raise Conflict("case version changed")
            action = disposition(request, Report.model_validate(run.report))
            decision = uuid4()
            data = {
                "workspace": scope.workspace_id,
                "id": scope.investigation_id,
                "case": run.case_id,
                "analyst": scope.analyst_id,
                "decision": decision,
                "operation": request.operation,
                "action": action,
                "version": version,
                "key": key,
                "payload": json.dumps(fingerprint),
                "note": request.note.strip(),
            }
            connection.execute(
                text("""
                INSERT INTO operations.decisions
                    (workspace_id, id, case_id, investigation_id, analyst_id, operation,
                     disposition, prior_case_version, idempotency_key, request_payload)
                VALUES (:workspace, :decision, :case, :id, :analyst, :operation,
                        :action, :version, :key, CAST(:payload AS jsonb))
            """),
                data,
            )
            if data["note"]:
                connection.execute(
                    text("""
                    INSERT INTO operations.notes (workspace_id, case_id, analyst_id, body)
                    VALUES (:workspace, :case, :analyst, :note)
                """),
                    data,
                )
            connection.execute(
                text("""
                UPDATE operations.investigations SET status = 'resume' WHERE id = :id
            """),
                data,
            )
            event(
                connection,
                scope,
                "decision",
                "decision_recorded",
                {
                    "decision_id": str(decision),
                    "disposition": action,
                },
            )
            # The checkpoint retains the original graph actor and decision retains its own actor.
            self.enqueue(connection, scope)
            return decision

    @staticmethod
    def enqueue(connection: Connection, scope: ToolScope) -> None:
        connection.execute(
            text("""
            INSERT INTO operations.agent_jobs (workspace_id, investigation_id, analyst_id)
            VALUES (:workspace, :id, :analyst) ON CONFLICT (investigation_id) DO NOTHING
        """),
            {
                "workspace": scope.workspace_id,
                "id": scope.investigation_id,
                "analyst": scope.analyst_id,
            },
        )

    def work_once(self) -> bool:
        # A session lock covers graph execution and is released by Postgres on disconnect.
        with checkpoint_connection(self.settings.database_url) as connection:
            claimed = connection.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired", (WORKER_LOCK,)
            ).fetchone()
            if not claimed or not claimed["acquired"]:
                return False
            with self.engine.connect() as db:
                job = (
                    db.execute(
                        text("""
                    SELECT workspace_id, analyst_id, investigation_id FROM operations.agent_jobs
                    ORDER BY queued_at, investigation_id LIMIT 1
                """)
                    )
                    .mappings()
                    .one_or_none()
                )
            if job is None:
                return False
            scope = ToolScope.model_validate(dict(job))
            try:
                self._process(connection, scope)
            except OperationalError:
                # Leave the job durable when the database or connection is unavailable.
                raise
            except WorkspaceAccessDenied:
                self._dequeue(scope)
            except Exception:
                log.exception("Investigation worker failed for %s", scope.investigation_id)
                with self.scoped(scope) as db:
                    run = locked_run(db, scope)
                    # A recorded human decision stays durable and retries on next startup.
                    if run.status == "resume":
                        raise
                    if run.status not in {"review", "complete"}:
                        db.execute(
                            text("""
                            UPDATE operations.investigations SET status = 'failed' WHERE id = :id
                        """),
                            {"id": scope.investigation_id},
                        )
                        db.execute(
                            text("""
                            UPDATE operations.cases SET status = 'queued', version = version + 1
                            WHERE id = :case
                        """),
                            {"case": run.case_id},
                        )
                        event(db, scope, "failed", "failed", {"summary": "Investigation failed."})
                self._dequeue(scope)
            return True

    def _dequeue(self, scope: ToolScope) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""
                DELETE FROM operations.agent_jobs WHERE investigation_id = :id
            """),
                {"id": scope.investigation_id},
            )

    def _process(self, connection: Any, scope: ToolScope) -> None:
        from langgraph.checkpoint.postgres import PostgresSaver

        config = {"configurable": {"thread_id": str(scope.investigation_id)}, "recursion_limit": 32}
        graph = build_graph(self.steps, PostgresSaver(connection))
        snapshot = graph.get_state(config)
        with self.scoped(scope) as db:
            run = locked_run(db, scope)
            if run.status == "review":
                raise Conflict("unexpected queued job for investigation in review")
            if run.status == "resume":
                decision = db.execute(
                    text("""
                    SELECT id FROM operations.decisions WHERE investigation_id = :id
                """),
                    {"id": scope.investigation_id},
                ).scalar_one()
                if snapshot.interrupts:
                    graph_input: Any = Command(resume=str(decision))
                elif snapshot.next:
                    graph_input = None
                else:
                    raise Conflict("missing approval checkpoint")
            elif run.status == "complete":
                graph_input = None
            else:
                db.execute(
                    text("""
                    UPDATE operations.investigations
                    SET status = 'running', started_at = coalesce(started_at, now())
                    WHERE id = :id
                """),
                    {"id": scope.investigation_id},
                )
                graph_input = None if snapshot.values else {"scope": scope.model_dump(mode="json")}

        if graph_input is not None or snapshot.next:
            graph.invoke(graph_input, config, durability="sync")
        after = graph.get_state(config)
        with self.scoped(scope) as db:
            run = locked_run(db, scope)
            if after.interrupts and run.status == "running":
                db.execute(
                    text("""
                    UPDATE operations.cases SET status = 'review', version = version + 1
                    WHERE id = :case
                """),
                    {"case": run.case_id},
                )
                db.execute(
                    text("""
                    UPDATE operations.investigations SET status = 'review' WHERE id = :id
                """),
                    {"id": scope.investigation_id},
                )
                event(db, scope, "review", "report_ready", {"report": run.report})
            elif run.status != "complete":
                raise Conflict("graph reached no approval checkpoint")
            # Delete in the same transaction that publishes review or completion to callers.
            db.execute(
                text("""
                DELETE FROM operations.agent_jobs WHERE investigation_id = :id
            """),
                {"id": scope.investigation_id},
            )

    def snapshot(
        self, scope: ToolScope, after: int = 0
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self.scoped(scope) as db:
            # One repeatable read snapshot is unnecessary: an extra poll after a terminal
            # marker covers events that committed between the two queries.
            item = (
                db.execute(
                    text("""
                SELECT i.status, i.mode, i.report, c.version AS case_version
                FROM operations.investigations AS i JOIN operations.cases AS c
                    ON (i.workspace_id, i.case_id) = (c.workspace_id, c.id)
                WHERE i.id = :id
            """),
                    {"id": scope.investigation_id},
                )
                .mappings()
                .one_or_none()
            )
            if item is None:
                raise InvestigationUnavailable
            events = db.execute(
                text("""
                SELECT sequence, kind, payload FROM operations.investigation_events
                WHERE investigation_id = :id AND sequence > :after
                ORDER BY sequence LIMIT 50
            """),
                {"id": scope.investigation_id, "after": after},
            ).mappings()
            return dict(item), [dict(row) for row in events]
