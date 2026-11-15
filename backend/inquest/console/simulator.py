from bisect import bisect_right
from json import dumps
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Connection, Engine, Row, text

from inquest.auth.api import Identity
from inquest.console.prepare import ReplayFixture
from inquest.db.tenant import TenantDatabase
from inquest.investigation.runtime import Conflict
from inquest.scoring.model import Score

BATCH = 500


def contributions_json(score: Score) -> str:
    return dumps([item.model_dump(mode="json") for item in score.top_contributions])


class ReplayStatus(BaseModel):
    replay_id: UUID | None = None
    state: Literal["idle", "paused", "running", "complete"] = "idle"
    cursor: int = 0
    total: int


class ReplayCommand(BaseModel):
    command: Literal["start", "pause", "replay"]
    expected_replay_id: UUID | None = None


class Simulator:
    def __init__(self, engine: Engine, tenants: TenantDatabase, fixture: ReplayFixture) -> None:
        self.engine = engine
        self.tenants = tenants
        self.fixture = fixture
        self.sequences = [item.sequence for item in fixture.alerts]
        if self.sequences != sorted(set(self.sequences)) or any(
            not alert.score.flagged or not 1 <= alert.sequence <= fixture.total
            for alert in fixture.alerts
        ):
            raise ValueError("Replay alerts must be unique, ordered and above the scorer threshold")
        self.flagged = frozenset(self.sequences)

    @staticmethod
    def current(connection: Connection, workspace: UUID) -> Row[tuple[UUID, str, int]] | None:
        return connection.execute(
            text("""
                SELECT r.id AS replay_id, r.state, r.cursor
                FROM operations.replay_jobs AS j
                JOIN operations.replay_runs AS r ON r.id = j.replay_id
                WHERE j.workspace_id = :workspace
            """),
            {"workspace": workspace},
        ).one_or_none()

    def status(self, identity: Identity) -> ReplayStatus:
        with self.tenants.transaction(workspace_id=identity[0], analyst_id=identity[1]) as db:
            row = self.current(db, identity[0])
        return (
            ReplayStatus.model_validate(dict(row._mapping) | {"total": self.fixture.total})
            if row
            else ReplayStatus(total=self.fixture.total)
        )

    @staticmethod
    def lock(connection: Connection, workspace: UUID) -> None:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:workspace, 7523))"),
            {"workspace": str(workspace)},
        )

    def command(self, identity: Identity, action: ReplayCommand) -> ReplayStatus:
        workspace, analyst = identity
        with self.tenants.transaction(workspace_id=workspace, analyst_id=analyst) as db:
            self.lock(db, workspace)
            prior = self.current(db, workspace)
            if action.expected_replay_id != (prior.replay_id if prior else None):
                raise Conflict("Simulator changed. Refresh and try again.")
            params = {
                "workspace": workspace,
                "analyst": analyst,
                "dataset": self.fixture.dataset_id,
            }
            if action.command == "replay" or (prior is None and action.command == "start"):
                replay_id = uuid4()
                db.execute(
                    text("""
                        INSERT INTO operations.replay_runs (id, workspace_id, dataset_id, state)
                        VALUES (:replay, :workspace, :dataset, 'running')
                    """),
                    params | {"replay": replay_id},
                )
                db.execute(
                    text("""
                        INSERT INTO operations.replay_jobs
                        VALUES (:workspace, :analyst, :replay, now())
                        ON CONFLICT (workspace_id) DO UPDATE
                        SET analyst_id = EXCLUDED.analyst_id,
                            replay_id = EXCLUDED.replay_id, due_at = EXCLUDED.due_at
                    """),
                    params | {"replay": replay_id},
                )
                if prior and prior.state == "running":
                    db.execute(
                        text("UPDATE operations.replay_runs SET state = 'paused' WHERE id = :old"),
                        {"old": prior.replay_id},
                    )
            elif prior and prior.state != "complete":
                running = action.command == "start"
                db.execute(
                    text("UPDATE operations.replay_runs SET state = :state WHERE id = :replay"),
                    {"state": "running" if running else "paused", "replay": prior.replay_id},
                )
                db.execute(
                    text("""
                        UPDATE operations.replay_jobs SET due_at = CASE WHEN :running
                            THEN coalesce(due_at, now()) END WHERE workspace_id = :workspace
                    """),
                    {"workspace": workspace, "running": running},
                )
        return self.status(identity)

    def work_once(self) -> bool:
        with self.engine.connect() as db:
            job = db.execute(
                text("""
                    SELECT workspace_id, analyst_id, replay_id FROM operations.replay_jobs
                    WHERE due_at <= now() ORDER BY due_at, workspace_id LIMIT 1
                """)
            ).one_or_none()
        if job is None:
            return False
        with self.tenants.transaction(
            workspace_id=job.workspace_id, analyst_id=job.analyst_id
        ) as db:
            self.lock(db, job.workspace_id)
            current = db.execute(
                text("""
                    SELECT r.cursor FROM operations.replay_jobs j
                    JOIN operations.replay_runs r ON r.id = j.replay_id
                    WHERE j.workspace_id = :workspace AND j.replay_id = :replay
                        AND j.due_at <= now()
                """),
                {"workspace": job.workspace_id, "replay": job.replay_id},
            ).scalar_one_or_none()
            if current is None:
                return False
            end = min(current + BATCH, self.fixture.total)
            self._publish_alerts(db, job.workspace_id, job.replay_id, current, end)
            complete = end == self.fixture.total
            db.execute(
                text(
                    "UPDATE operations.replay_runs SET cursor = :cursor, state = :state "
                    "WHERE id = :id"
                ),
                {
                    "cursor": end,
                    "state": "complete" if complete else "running",
                    "id": job.replay_id,
                },
            )
            db.execute(
                text("""
                    UPDATE operations.replay_jobs
                    SET due_at = CASE WHEN NOT :complete THEN now() + interval '2 seconds' END
                    WHERE workspace_id = :workspace
                """),
                {"complete": complete, "workspace": job.workspace_id},
            )
        return True

    def _publish_alerts(
        self, db: Connection, workspace: UUID, replay: UUID, cursor: int, end: int
    ) -> None:
        start_index = bisect_right(self.sequences, cursor)
        end_index = bisect_right(self.sequences, end)
        rows = [
            {
                "workspace": workspace,
                "replay": replay,
                "dataset": self.fixture.dataset_id,
                "sequence": alert.sequence,
                "model": alert.score.model_version,
                "feature": alert.score.feature_version,
                "score": alert.score.fraud_probability,
                "threshold": alert.score.threshold,
                "contributions": contributions_json(alert.score),
            }
            for alert in self.fixture.alerts[start_index:end_index]
        ]
        if not rows:
            return
        db.execute(
            text("""
                INSERT INTO operations.transaction_scores
                VALUES (:replay, :dataset, :sequence, :model, :feature, :score,
                        :threshold, CAST(:contributions AS jsonb))
            """),
            rows,
        )
        db.execute(
            text("""
                INSERT INTO operations.cases
                    (workspace_id, replay_id, dataset_id, source_sequence, model_version)
                VALUES (:workspace, :replay, :dataset, :sequence, :model)
            """),
            rows,
        )
