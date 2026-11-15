import json
import os
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from inquest.auth.api import authenticate
from inquest.db.tenant import TenantDatabase
from inquest.investigation.api import investigation_router
from inquest.investigation.contracts import ToolScope
from inquest.investigation.demo import DemoSession, provision
from inquest.investigation.graph import Steps
from inquest.investigation.policy import PolicyIndex
from inquest.investigation.provider import Completion, ModelGateway, ResponseCache
from inquest.investigation.replay import Recordings
from inquest.investigation.runtime import Conflict, DecisionRequest
from inquest.investigation.service import Investigations
from inquest.investigation.tools import InvestigationTools
from inquest.settings import Settings

requires_db = pytest.mark.skipif(
    os.getenv("INQUEST_TEST_POSTGRES") != "1", reason="requires migrated Postgres"
)


@pytest.fixture
def demo() -> Iterator[DemoSession]:
    case = provision(150)
    yield case
    settings = Settings()
    owner = create_engine(settings.migration_database_url)
    try:
        with owner.begin() as connection:
            params = {"workspace": UUID(case.workspace_id), "analyst": UUID(case.analyst_id)}
            run_ids = (
                connection.execute(
                    text("""
                SELECT id FROM operations.investigations WHERE workspace_id = :workspace
            """),
                    params,
                )
                .scalars()
                .all()
            )
            replay = connection.execute(
                text("""
                SELECT replay_id FROM operations.cases WHERE workspace_id = :workspace
            """),
                params,
            ).scalar_one()
            for table in (
                "agent_jobs",
                "investigation_events",
                "tool_calls",
                "notes",
                "decisions",
                "investigations",
                "cases",
                "analyst_sessions",
                "workspace_usage",
                "workspace_memberships",
            ):
                connection.execute(
                    text(f"DELETE FROM operations.{table} WHERE workspace_id = :workspace"), params
                )
            connection.execute(
                text("DELETE FROM operations.transaction_scores WHERE replay_id = :id"),
                {"id": replay},
            )
            connection.execute(
                text("DELETE FROM operations.replay_runs WHERE id = :id"), {"id": replay}
            )
            connection.execute(text("DELETE FROM operations.analysts WHERE id = :analyst"), params)
            connection.execute(
                text("DELETE FROM operations.workspaces WHERE id = :workspace"), params
            )
            for run_id in run_ids:
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    connection.execute(
                        text(f"DELETE FROM agent_checkpoints.{table} WHERE thread_id = :id"),
                        {"id": str(run_id)},
                    )
    finally:
        owner.dispose()


def service(gateway: ModelGateway | None = None) -> Investigations:
    settings = Settings()
    engine = create_engine(settings.database_url)
    tenant = TenantDatabase(engine)
    tools = InvestigationTools(
        tenant, create_engine(settings.tool_database_url), PolicyIndex(settings.policy_directory)
    )
    return Investigations(
        engine,
        Steps(
            tenant,
            tools,
            gateway,
            2**31 - 1,
            Recordings(settings.recordings_file),
        ),
        settings,
    )


@requires_db
def test_api_replay_checkpoint_and_resume_through_fresh_worker(demo: DemoSession) -> None:
    runtime = service()
    app = FastAPI()
    app.include_router(
        investigation_router(
            runtime, b"test-secret", authenticate(runtime.auth, Settings().web_origin)
        )
    )
    with TestClient(app) as client:
        path = f"/api/v1/cases/{demo.case_id}/investigations"
        assert client.post(path, headers={"Idempotency-Key": "start-test"}).status_code == 401
        headers = {"Authorization": f"Bearer {demo.token}", "Idempotency-Key": "start-test"}
        response = client.post(path, headers=headers)
        assert response.status_code == 202, response.text
        assert client.post(path, headers=headers).json() == response.json()
        run_id = response.json()["investigation_id"]
        route = f"/api/v1/investigations/{run_id}"
        assert runtime.work_once()
        row = client.get(route, headers=headers).json()
        assert row["status"] == "review" and row["mode"] == "replay"
        assert row["report"]["evidence"]
        stream = client.get(f"{route}/events", headers=headers)
        assert stream.status_code == 200
        assert "event: tool_observed" in stream.text and "event: report_ready" in stream.text
        ids = [int(line[4:]) for line in stream.text.splitlines() if line.startswith("id: ")]
        assert ids == list(range(1, len(ids) + 1))
        resumed = client.get(f"{route}/events", headers=headers | {"Last-Event-ID": str(ids[-2])})
        assert "event: report_ready" in resumed.text and "event: tool_observed" not in resumed.text

        decision_headers = headers | {"Idempotency-Key": "decision-test"}
        body = {"operation": "approve", "expected_case_version": row["case_version"]}
        assert (
            client.post(
                f"{route}/decision",
                headers=decision_headers,
                json=body | {"expected_case_version": 0},
            ).status_code
            == 409
        )
        recorded = client.post(f"{route}/decision", headers=decision_headers, json=body)
        assert recorded.status_code == 202, recorded.text
        assert service().work_once()
        assert client.get(route, headers=headers).json()["status"] == "complete"
        assert (
            client.post(f"{route}/decision", headers=decision_headers, json=body).json()
            == recorded.json()
        )
        assert (
            client.post(
                f"{route}/decision", headers=decision_headers, json=body | {"note": "changed"}
            ).status_code
            == 409
        )


class RepairProvider:
    identity = "test:repair"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, output_tokens: int, timeout: float) -> Completion:
        self.calls += 1
        if "Select one useful tool" in prompt:
            return Completion(content='{"tool":"done"}', tokens=80)
        context = json.loads(prompt.split("\n", 1)[1])
        evidence_id = context["observations"][0]["evidence_id"]
        return Completion(
            content=json.dumps(
                {
                    "verdict": "needs_human_review",
                    "confidence": 0.5,
                    "recommended_action": "escalate",
                    "evidence": [
                        {
                            "evidence_id": evidence_id,
                            "field": "transaction.source_sequence",
                            "value": 150 if "Repair:" in prompt else 999,
                        }
                    ],
                }
            ),
            tokens=130,
        )


@requires_db
def test_agent_repairs_unsupported_fact_and_cannot_self_approve(
    demo: DemoSession,
    tmp_path: Path,
) -> None:
    provider = RepairProvider()
    runtime = service(ModelGateway(provider, ResponseCache(tmp_path / "cache.sqlite")))
    owner = create_engine(Settings().migration_database_url)
    with owner.begin() as connection:
        enabled = connection.execute(
            text("SELECT llm_enabled FROM operations.runtime_controls WHERE singleton")
        ).scalar_one()
        connection.execute(text("UPDATE operations.runtime_controls SET llm_enabled = true"))
    try:
        scope = ToolScope(
            workspace_id=UUID(demo.workspace_id),
            analyst_id=UUID(demo.analyst_id),
            investigation_id=uuid4(),
        )
        with pytest.raises(Conflict):
            # Supply an incompatible case state through the normal API once a run is queued.
            runtime.start(
                scope, UUID(demo.case_id), "first-key", sha256(demo.token.encode()).hexdigest()
            )
            runtime.decide(
                scope,
                DecisionRequest(operation="approve", expected_case_version=1),
                "early-decision",
            )
        assert runtime.work_once()
        row, _ = runtime.snapshot(scope)
        assert provider.calls == 3
        assert row["status"] == "review" and row["mode"] == "live"
        assert row["report"]["status"] == "verified"
        assert row["report"]["evidence"][0]["value"] == 150
        with runtime.scoped(scope) as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM operations.decisions")).scalar_one()
                == 0
            )
    finally:
        with owner.begin() as connection:
            connection.execute(
                text("UPDATE operations.runtime_controls SET llm_enabled = :enabled"),
                {"enabled": enabled},
            )
        owner.dispose()


@requires_db
def test_global_cap_falls_back_without_sending_provider_request(
    demo: DemoSession,
    tmp_path: Path,
) -> None:
    provider = RepairProvider()
    runtime = service(ModelGateway(provider, ResponseCache(tmp_path / "cache.sqlite")))
    runtime.steps.daily_tokens = 1
    owner = create_engine(Settings().migration_database_url)
    with owner.begin() as connection:
        enabled = connection.execute(
            text("SELECT llm_enabled FROM operations.runtime_controls WHERE singleton")
        ).scalar_one()
        connection.execute(text("UPDATE operations.runtime_controls SET llm_enabled = true"))
    try:
        scope = ToolScope(
            workspace_id=UUID(demo.workspace_id),
            analyst_id=UUID(demo.analyst_id),
            investigation_id=uuid4(),
        )
        runtime.start(scope, UUID(demo.case_id), "budget-test", uuid4().hex)
        assert runtime.work_once()
        row, events = runtime.snapshot(scope)
        assert row["status"] == "review" and row["mode"] == "replay"
        assert provider.calls == 0
        assert any(item["kind"] == "recording_used" for item in events)
    finally:
        with owner.begin() as connection:
            connection.execute(
                text("UPDATE operations.runtime_controls SET llm_enabled = :enabled"),
                {"enabled": enabled},
            )
        owner.dispose()


@requires_db
def test_unknown_case_counts_toward_investigation_start_rate_limit(demo: DemoSession) -> None:
    runtime = service()
    runtime.settings.investigate_per_ip_minute = 1
    caller = ToolScope(
        workspace_id=UUID(demo.workspace_id),
        analyst_id=UUID(demo.analyst_id),
        investigation_id=uuid4(),
    )
    # The first attempt counts even if the requested case does not exist.
    from inquest.investigation.repository import InvestigationUnavailable
    from inquest.investigation.runtime import RateLimited

    ip = uuid4().hex
    with pytest.raises(InvestigationUnavailable):
        runtime.start(caller, uuid4(), "unknown-case", ip)
    with pytest.raises(RateLimited):
        runtime.start(caller, UUID(demo.case_id), "valid-case", ip)
