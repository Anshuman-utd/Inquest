import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from psycopg import Error
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from inquest.db.tenant import TenantDatabase, WorkspaceAccessDenied
from inquest.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("INQUEST_TEST_POSTGRES") != "1",
    reason="requires migrated Postgres (INQUEST_TEST_POSTGRES=1)",
)


@dataclass(frozen=True)
class WorkspacePair:
    first: UUID
    second: UUID
    analyst: UUID
    other_analyst: UUID
    other_case: UUID
    other_investigation: UUID


@pytest.fixture
def api_engine() -> Iterator[Engine]:
    engine = create_engine(Settings().database_url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def workspaces() -> Iterator[WorkspacePair]:
    engine = create_engine(Settings().migration_database_url)
    pair = WorkspacePair(*(uuid4() for _ in range(6)))
    data = {
        "first": pair.first,
        "second": pair.second,
        "analyst": pair.analyst,
        "other": pair.other_analyst,
        "case": pair.other_case,
        "investigation": pair.other_investigation,
        "dataset": str(uuid4()),
        "replay": uuid4(),
    }
    setup = [
        "INSERT INTO operations.workspaces VALUES (:first), (:second)",
        "INSERT INTO operations.analysts VALUES (:analyst, :dataset || '-1'), "
        "(:other, :dataset || '-2')",
        "INSERT INTO operations.workspace_memberships VALUES (:first, :analyst), (:second, :other)",
        """INSERT INTO fixture.datasets VALUES (:dataset, 0, '{}')""",
        "INSERT INTO fixture.cities VALUES (:dataset, 'city', 'Pune', 18.52, 73.86)",
        "INSERT INTO fixture.customers VALUES (:dataset, 'customer', 'Customer', 'city')",
        """INSERT INTO fixture.merchants
           VALUES (:dataset, 'merchant', 'Merchant', 'retail', 'city', 'standard')""",
        "INSERT INTO fixture.devices VALUES (:dataset, 'device')",
        """INSERT INTO fixture.transactions VALUES (
            :dataset, 1, 'customer', 'merchant', 'device', 'instrument', 'city',
            'physical', now(), 5000, 'INR', 'card', 'purchase', false, false
        )""",
        """INSERT INTO operations.replay_runs (id, dataset_id) VALUES (:replay, :dataset)""",
        """INSERT INTO operations.transaction_scores
           VALUES (:replay, :dataset, 1, 'm', 'f', 0.8, 0.5, '[]')""",
        """INSERT INTO operations.cases
           (workspace_id, id, replay_id, dataset_id, source_sequence, model_version)
           VALUES (:second, :case, :replay, :dataset, 1, 'm')""",
        """INSERT INTO operations.investigations (workspace_id, id, case_id, mode)
           VALUES (:second, :investigation, :case, 'replay')""",
        """INSERT INTO operations.notes (workspace_id, case_id, analyst_id, body)
           VALUES (:second, :case, :other, 'Synthetic note')""",
        """INSERT INTO operations.decisions
           (workspace_id, case_id, investigation_id, analyst_id, operation,
            disposition, prior_case_version, idempotency_key)
           VALUES (:second, :case, :investigation, :other, 'approve', 'release', 0, 'test')""",
    ]
    try:
        with engine.begin() as connection:
            for statement in setup:
                connection.execute(text(statement), data)
        yield pair
    finally:
        with engine.begin() as connection:
            for table in ("decisions", "notes", "investigations", "cases", "workspace_memberships"):
                connection.execute(
                    text(f"DELETE FROM operations.{table} WHERE workspace_id IN (:first, :second)"),
                    data,
                )
            for table in ("transaction_scores", "replay_runs"):
                connection.execute(
                    text(f"DELETE FROM operations.{table} WHERE dataset_id = :dataset"), data
                )
            for table in ("transactions", "devices", "merchants", "customers", "cities"):
                connection.execute(
                    text(f"DELETE FROM fixture.{table} WHERE dataset_id = :dataset"), data
                )
            connection.execute(text("DELETE FROM fixture.datasets WHERE id = :dataset"), data)
            connection.execute(
                text("DELETE FROM operations.analysts WHERE id IN (:analyst, :other)"), data
            )
            connection.execute(
                text("DELETE FROM operations.workspaces WHERE id IN (:first, :second)"), data
            )
        engine.dispose()


def test_membership_and_pooled_connection_isolation(
    api_engine: Engine, workspaces: WorkspacePair
) -> None:
    database = TenantDatabase(api_engine)
    with (
        pytest.raises(WorkspaceAccessDenied),
        database.transaction(workspace_id=workspaces.second, analyst_id=workspaces.analyst),
    ):
        pytest.fail("Cross-workspace membership check allowed access")

    for workspace_id, analyst_id, expected in (
        (workspaces.second, workspaces.other_analyst, 1),
        (workspaces.first, workspaces.analyst, 0),
    ):
        with database.transaction(workspace_id=workspace_id, analyst_id=analyst_id) as connection:
            for table in ("cases", "investigations", "decisions", "notes"):
                assert (
                    connection.execute(
                        text(f"SELECT count(*) FROM operations.{table}")
                    ).scalar_one()
                    == expected
                )
            assert (
                connection.execute(text("SELECT count(*) FROM fixture.transactions")).scalar_one()
                >= 1
            )
    with api_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM operations.cases")).scalar_one() == 0


def test_cross_workspace_update_and_reference(
    api_engine: Engine, workspaces: WorkspacePair
) -> None:
    database = TenantDatabase(api_engine)
    with database.transaction(
        workspace_id=workspaces.first, analyst_id=workspaces.analyst
    ) as connection:
        changed = connection.execute(
            text("UPDATE operations.cases SET status = 'resolved' WHERE id = :case RETURNING id"),
            {"case": workspaces.other_case},
        )
        assert changed.scalar_one_or_none() is None
    with (
        pytest.raises(IntegrityError) as error,
        database.transaction(
            workspace_id=workspaces.first, analyst_id=workspaces.analyst
        ) as connection,
    ):
        connection.execute(
            text("""
                INSERT INTO operations.investigations (workspace_id, case_id, mode)
                VALUES (:workspace, :case, 'replay')
            """),
            {"workspace": workspaces.first, "case": workspaces.other_case},
        )
    assert isinstance(error.value.orig, Error)
    assert error.value.orig.sqlstate == "23503"


def test_runtime_cannot_write_fixture_or_read_truth(api_engine: Engine) -> None:
    for statement in (
        """INSERT INTO fixture.datasets VALUES ('unauthorized', 0, '{}')""",
        "SELECT * FROM evaluation.truth",
    ):
        with pytest.raises(ProgrammingError) as error, api_engine.begin() as connection:
            connection.execute(text(statement))
        assert isinstance(error.value.orig, Error)
        assert error.value.orig.sqlstate == "42501"


def test_foreign_workspace_insert_is_blocked(api_engine: Engine, workspaces: WorkspacePair) -> None:
    database = TenantDatabase(api_engine)
    with (
        pytest.raises(ProgrammingError) as error,
        database.transaction(
            workspace_id=workspaces.first, analyst_id=workspaces.analyst
        ) as connection,
    ):
        connection.execute(
            text("""
                INSERT INTO operations.notes (workspace_id, case_id, analyst_id, body)
                VALUES (:workspace, :case, :analyst, 'Synthetic note')
            """),
            {
                "workspace": workspaces.second,
                "case": workspaces.other_case,
                "analyst": workspaces.other_analyst,
            },
        )
    assert isinstance(error.value.orig, Error)
    assert error.value.orig.sqlstate == "42501"
