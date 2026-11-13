import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg import Error
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError

from inquest.db.tenant import TenantDatabase, WorkspaceAccessDenied
from inquest.investigation.contracts import (
    CustomerHistoryObservation,
    CustomerProfileObservation,
    DatabaseEvidence,
    DeviceObservation,
    GeoObservation,
    MerchantObservation,
    ToolScope,
    TransactionObservation,
    VelocityObservation,
)
from inquest.investigation.policy import PolicyEvidence, PolicyIndex
from inquest.investigation.repository import InvestigationUnavailable
from inquest.investigation.tools import TOOL_REQUESTS, InvestigationTools
from inquest.settings import Settings

AT = datetime(2025, 3, 1, 12, tzinfo=UTC)
FOCAL = 26
requires_db = pytest.mark.skipif(
    os.getenv("INQUEST_TEST_POSTGRES") != "1", reason="requires migrated Postgres"
)


@dataclass(frozen=True)
class CaseFixture:
    scope: ToolScope
    other_workspace: UUID
    other_analyst: UUID
    remote_investigation: UUID
    replay_id: UUID
    tools: InvestigationTools
    tool_engine: Engine


@pytest.fixture
def case() -> Iterator[CaseFixture]:
    settings = Settings()
    api = create_engine(settings.database_url)
    reader = create_engine(settings.tool_database_url)
    owner = create_engine(settings.migration_database_url)
    dataset = str(uuid4())
    scope = ToolScope(workspace_id=uuid4(), analyst_id=uuid4(), investigation_id=uuid4())
    other, other_analyst, replay, case_id, remote_case, remote_investigation = (
        uuid4() for _ in range(6)
    )
    params = {
        "dataset": dataset,
        "workspace": scope.workspace_id,
        "analyst": scope.analyst_id,
        "investigation": scope.investigation_id,
        "other": other,
        "other_analyst": other_analyst,
        "replay": replay,
        "case": case_id,
        "remote_case": remote_case,
        "remote_investigation": remote_investigation,
    }
    setup = (
        "INSERT INTO operations.workspaces VALUES (:workspace), (:other)",
        """INSERT INTO operations.analysts
           VALUES (:analyst, :dataset || '-1'), (:other_analyst, :dataset || '-2')""",
        """INSERT INTO operations.workspace_memberships
           VALUES (:workspace, :analyst), (:other, :other_analyst)""",
        "INSERT INTO fixture.datasets VALUES (:dataset, 0, '{}')",
        """INSERT INTO fixture.cities VALUES
           (:dataset, 'pune', 'Pune', 18.52, 73.86),
           (:dataset, 'delhi', 'Delhi', 28.61, 77.20)""",
        """INSERT INTO fixture.customers VALUES
           (:dataset, 'customer', 'Customer', 'pune'),
           (:dataset, 'peer', 'Peer', 'delhi')""",
        """INSERT INTO fixture.merchants
           VALUES (:dataset, 'shop', 'Shop', 'transfer', 'pune', 'elevated')""",
        "INSERT INTO fixture.devices VALUES (:dataset, 'device'), (:dataset, 'alternate')",
    )
    # 21 background attempts at 10 days, one outside the window, and a recent burst.
    payments = [
        (i, AT - timedelta(days=10), "customer", "alternate", None, False) for i in range(1, 22)
    ] + [
        (22, AT - timedelta(days=31), "customer", "device", "pune", False),
        (23, AT - timedelta(minutes=5), "customer", "device", "pune", True),
        (24, AT - timedelta(minutes=1), "peer", "device", "pune", False),
        (25, AT, "customer", "alternate", "pune", False),
        (FOCAL, AT, "customer", "device", "delhi", False),
        (27, AT, "customer", "device", None, False),
        (28, AT + timedelta(seconds=1), "customer", "device", None, True),
        # A deliberately out-of-order source row. Its timestamp is earlier than the focal
        # payment, but the replay has yet to ingest it.
        (29, AT - timedelta(seconds=2), "customer", "device", "pune", True),
    ]
    with owner.begin() as connection:
        for statement in setup:
            connection.execute(text(statement), params)
        connection.execute(
            text("""
                INSERT INTO fixture.transactions VALUES (
                    :dataset, :sequence, :customer, 'shop', :device, :customer,
                    :city, :location, :occurred, 5000, 'INR', 'upi', 'push', :declined, false
                )
            """),
            [
                params
                | {
                    "sequence": sequence,
                    "customer": customer,
                    "device": device,
                    "city": city,
                    "location": "physical" if city is not None else "remote",
                    "occurred": occurred,
                    "declined": declined,
                }
                for sequence, occurred, customer, device, city, declined in payments
            ],
        )
        for statement in (
            """INSERT INTO operations.replay_runs (id, dataset_id, cursor)
               VALUES (:replay, :dataset, 27)""",
            """INSERT INTO operations.transaction_scores VALUES
               (:replay, :dataset, 26, 'm', 'f', 0.8, 0.5, '[]'),
               (:replay, :dataset, 27, 'm', 'f', 0.8, 0.5, '[]')""",
            """INSERT INTO operations.cases
               (workspace_id, id, replay_id, dataset_id, source_sequence, model_version)
               VALUES (:workspace, :case, :replay, :dataset, 26, 'm'),
                      (:workspace, :remote_case, :replay, :dataset, 27, 'm')""",
            """INSERT INTO operations.investigations (workspace_id, id, case_id, mode)
               VALUES (:workspace, :investigation, :case, 'replay'),
                      (:workspace, :remote_investigation, :remote_case, 'replay')""",
        ):
            connection.execute(text(statement), params)
    try:
        yield CaseFixture(
            scope,
            other,
            other_analyst,
            remote_investigation,
            replay,
            InvestigationTools(TenantDatabase(api), reader, PolicyIndex(Path("policies"))),
            reader,
        )
    finally:
        with owner.begin() as connection:
            for table in ("investigations", "cases", "workspace_memberships"):
                connection.execute(
                    text(
                        f"DELETE FROM operations.{table} WHERE workspace_id IN (:workspace, :other)"
                    ),
                    params,
                )
            for table in ("transaction_scores", "replay_runs"):
                connection.execute(
                    text(f"DELETE FROM operations.{table} WHERE dataset_id = :dataset"), params
                )
            for table in ("transactions", "devices", "merchants", "customers", "cities"):
                connection.execute(
                    text(f"DELETE FROM fixture.{table} WHERE dataset_id = :dataset"), params
                )
            connection.execute(text("DELETE FROM fixture.datasets WHERE id = :dataset"), params)
            connection.execute(
                text("DELETE FROM operations.analysts WHERE id IN (:analyst, :other_analyst)"),
                params,
            )
            connection.execute(
                text("DELETE FROM operations.workspaces WHERE id IN (:workspace, :other)"), params
            )
        api.dispose()
        reader.dispose()
        owner.dispose()


@pytest.mark.parametrize(
    "arguments",
    [
        {"tool": "get_transaction", "dataset_id": "spoof"},
        {"tool": "velocity_check", "customer_id": "peer"},
        {"tool": "get_customer_history", "window_days": 31},
        {"tool": "get_customer_history", "window_days": "7"},
        {"tool": "get_customer_history", "window_days": True},
        {"tool": "execute_sql", "query": "SELECT 1"},
    ],
)
def test_tool_contract_rejects_scope_overrides_and_invalid_inputs(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TOOL_REQUESTS.validate_python(arguments)


@requires_db
def test_every_tool_returns_evidence_at_the_replay_cutoff(case: CaseFixture) -> None:
    calls: tuple[dict[str, object], ...] = (
        {"tool": "get_transaction"},
        {"tool": "get_customer_profile"},
        {"tool": "get_customer_history", "window_days": 30},
        {"tool": "velocity_check"},
        {"tool": "geo_mismatch_check"},
        {"tool": "device_check"},
        {"tool": "merchant_risk_lookup"},
    )
    results = [
        case.tools.execute(case.scope, index, arguments) for index, arguments in enumerate(calls, 1)
    ]
    observations = []
    assert len({item.evidence_id for item in results}) == len(calls)
    for result, arguments in zip(results, calls, strict=True):
        assert isinstance(result, DatabaseEvidence)
        assert DatabaseEvidence.model_validate_json(result.model_dump_json()) == result
        assert result.cutoff.dataset_id
        assert result.cutoff.source_sequence == FOCAL
        assert result.cutoff.occurred_at == AT
        assert result.observation.tool == arguments["tool"]
        observations.append(result.observation)
    assert case.tools.execute(case.scope, 1, calls[0]) == results[0]
    focal, profile, history, velocity, geo, device, merchant = observations
    assert isinstance(focal, TransactionObservation) and focal.transaction.source_sequence == FOCAL
    assert isinstance(profile, CustomerProfileObservation)
    assert profile.activity_30d.attempts == 23
    assert profile.average_amount_minor == 5000
    assert profile.distinct_devices_30d == 2
    assert isinstance(history, CustomerHistoryObservation)
    assert history.activity.attempts == 23 and history.truncated and len(history.attempts) == 20
    assert [row.source_sequence for row in history.attempts[:2]] == [25, 23]
    assert isinstance(velocity, VelocityObservation)
    assert (velocity.last_5m.attempts, velocity.last_5m.declines) == (2, 1)
    assert velocity.last_1h.total_minor == velocity.last_24h.total_minor == 10_000
    assert velocity.preceding_29d.attempts == 21
    assert isinstance(geo, GeoObservation) and geo.previous_physical_30d is not None
    assert geo.previous_physical_30d.source_sequence == 25
    assert geo.elapsed_seconds == 0 and geo.implied_speed_kmh is None
    assert geo.distance_from_home_km is not None and geo.distance_from_home_km > 1000
    assert isinstance(device, DeviceObservation)
    assert device.device_attempts_30d == 2 and device.customer_attempts_on_device_30d == 1
    assert device.distinct_instruments_1h == device.distinct_customers_1h == 2
    assert isinstance(merchant, MerchantObservation)
    assert merchant.distinct_customers_5m == 2 and merchant.upi_push_attempts_5m == 3
    assert merchant.same_amount_attempts_24h == 3 and merchant.merchant.risk_tier == "elevated"


@requires_db
def test_remote_payment_keeps_distance_unknown(case: CaseFixture) -> None:
    scope = case.scope.model_copy(update={"investigation_id": case.remote_investigation})
    result = case.tools.execute(scope, 1, {"tool": "geo_mismatch_check"})
    assert isinstance(result, DatabaseEvidence) and isinstance(result.observation, GeoObservation)
    assert result.observation.current_city is None
    assert result.observation.distance_from_home_km is None
    assert result.observation.implied_speed_kmh is None


@requires_db
def test_workspace_membership_and_scoped_investigation_are_required(case: CaseFixture) -> None:
    arguments: dict[str, object] = {"tool": "get_transaction"}
    with pytest.raises(WorkspaceAccessDenied):
        case.tools.execute(
            case.scope.model_copy(update={"workspace_id": case.other_workspace}), 1, arguments
        )
    with pytest.raises(InvestigationUnavailable):
        case.tools.execute(
            case.scope.model_copy(
                update={"workspace_id": case.other_workspace, "analyst_id": case.other_analyst}
            ),
            1,
            arguments,
        )


@requires_db
def test_tool_role_cannot_write_or_read_private_records(case: CaseFixture) -> None:
    for statement in (
        "UPDATE fixture.transactions SET declined = true WHERE false",
        "SELECT * FROM operations.notes",
        "SELECT * FROM evaluation.truth",
    ):
        with (
            pytest.raises(ProgrammingError) as failure,
            case.tool_engine.begin() as connection,
        ):
            connection.execute(text(statement))
        assert isinstance(failure.value.orig, Error) and failure.value.orig.sqlstate == "42501"


@requires_db
def test_policy_tool_shares_the_case_evidence_boundary(case: CaseFixture) -> None:
    arguments: dict[str, object] = {"tool": "search_policy_docs", "query": "card probing"}
    result = case.tools.execute(case.scope, 1, arguments)
    assert isinstance(result, PolicyEvidence)
    assert result.cutoff.source_sequence == FOCAL
    assert result.observation.matches[0].policy_id == "P04"
    assert case.tools.execute(case.scope, 1, arguments) == result
    with pytest.raises(InvestigationUnavailable):
        case.tools.execute(
            case.scope.model_copy(
                update={
                    "workspace_id": case.other_workspace,
                    "analyst_id": case.other_analyst,
                }
            ),
            1,
            arguments,
        )


@requires_db
def test_unprocessed_case_is_unavailable_and_replay_advance_cannot_change_evidence(
    case: CaseFixture,
) -> None:
    owner = create_engine(Settings().migration_database_url)
    arguments: dict[str, object] = {"tool": "velocity_check"}
    original = case.tools.execute(case.scope, 1, arguments)
    try:
        with owner.begin() as connection:
            connection.execute(
                text("UPDATE operations.replay_runs SET cursor = 29 WHERE id = :replay"),
                {"replay": case.replay_id},
            )
        assert case.tools.execute(case.scope, 1, arguments) == original
        with owner.begin() as connection:
            connection.execute(
                text("UPDATE operations.replay_runs SET cursor = 25 WHERE id = :replay"),
                {"replay": case.replay_id},
            )
        with pytest.raises(InvestigationUnavailable):
            case.tools.execute(case.scope, 1, arguments)
    finally:
        owner.dispose()


@requires_db
def test_database_failure_preserves_citable_scope(
    case: CaseFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import NoReturn

    from sqlalchemy.exc import OperationalError

    from inquest.investigation.contracts import UnavailableEvidence
    from inquest.investigation.repository import Observations

    def unavailable(_: Observations) -> NoReturn:
        raise OperationalError(None, None, OSError("database unavailable"))

    arguments: dict[str, object] = {"tool": "velocity_check"}
    original = case.tools.execute(case.scope, 1, arguments)
    with monkeypatch.context() as patch:
        patch.setattr(Observations, "velocity", unavailable)
        failed = case.tools.execute(case.scope, 1, arguments)
    assert isinstance(failed, UnavailableEvidence)
    assert failed.reason == "data_unavailable"
    assert failed.evidence_id == original.evidence_id and failed.cutoff == original.cutoff
    assert case.tools.execute(case.scope, 1, arguments) == original
