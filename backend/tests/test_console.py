import os
from collections.abc import Iterator
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from inquest.auth.api import hash_token
from inquest.console.api import console_router
from inquest.main import actor, settings, simulator


@pytest.fixture
def tokens() -> Iterator[tuple[str, str]]:
    engine = create_engine(settings.migration_database_url)
    accounts = []
    for _ in range(2):
        token = token_urlsafe(32)
        accounts.append(
            {
                "workspace": uuid4(),
                "analyst": uuid4(),
                "token": hash_token(token),
                "raw": token,
            }
        )
    try:
        with engine.begin() as conn:
            for account in accounts:
                for statement in (
                    "INSERT INTO operations.workspaces VALUES (:workspace)",
                    "INSERT INTO operations.analysts (id) VALUES (:analyst)",
                    "INSERT INTO operations.workspace_memberships VALUES (:workspace, :analyst)",
                    "INSERT INTO operations.analyst_sessions VALUES "
                    "(:token, :workspace, :analyst, now() + interval '1 hour')",
                ):
                    conn.execute(text(statement), account)
        yield accounts[0]["raw"], accounts[1]["raw"]  # type: ignore[misc]
    finally:
        with engine.begin() as conn:
            for account in accounts:
                for statement in (
                    "DELETE FROM operations.analyst_sessions WHERE workspace_id = :workspace",
                    "DELETE FROM operations.replay_jobs WHERE workspace_id = :workspace",
                    "DELETE FROM operations.cases WHERE workspace_id = :workspace",
                    "DELETE FROM operations.transaction_scores WHERE replay_id IN "
                    "(SELECT id FROM operations.replay_runs WHERE workspace_id = :workspace)",
                    "DELETE FROM operations.replay_runs WHERE workspace_id = :workspace",
                    "DELETE FROM operations.workspace_memberships WHERE workspace_id = :workspace",
                    "DELETE FROM operations.workspaces WHERE id = :workspace",
                    "DELETE FROM operations.analysts WHERE id = :analyst",
                ):
                    conn.execute(text(statement), account)
        engine.dispose()


@pytest.mark.skipif(os.getenv("INQUEST_TEST_POSTGRES") != "1", reason="requires migrated Postgres")
def test_replay_queue_and_explorer_respect_workspace(tokens: tuple[str, str]) -> None:
    app = FastAPI()
    app.include_router(console_router(simulator, actor))
    with TestClient(app) as client:
        first, second = ({"Authorization": f"Bearer {token}"} for token in tokens)
        assert client.get("/api/v1/cases").status_code == 401
        assert client.get("/api/v1/cases", headers=first).json()["items"] == []
        cmd = "/api/v1/simulator/commands"
        started = client.post(cmd, json={"command": "start"}, headers=first)
        assert started.status_code == 200, started.text
        replay_id = started.json()["replay_id"]
        assert client.get("/api/v1/simulator", headers=second).json()["state"] == "idle"

        assert simulator.work_once()
        page = client.get("/api/v1/cases", params={"limit": 1, "sort": "risk"}, headers=first)
        assert page.status_code == 200, page.text
        first_case = page.json()["items"][0]
        cursor = page.json()["next_cursor"]
        next_page = client.get(
            "/api/v1/cases",
            params={"after": cursor, "limit": 1, "sort": "risk"},
            headers=first,
        ).json()
        assert next_page["items"][0]["case_id"] != first_case["case_id"]
        detail = f"/api/v1/cases/{first_case['case_id']}"
        assert client.get(detail, headers=second).status_code == 404
        assert client.get("/api/v1/cases", headers=second).json()["items"] == []
        assert len(client.get(detail, headers=first).json()["contributions"]) == 5
        customer = first_case["customer_id"]
        results = client.get("/api/v1/customers", params={"q": customer}, headers=first).json()
        assert results[0]["id"] == customer
        history = client.get(f"/api/v1/customers/{customer}/transactions", headers=first)
        assert history.status_code == 200, history.text
        assert history.json()["customer"]["id"] == customer
        paused = client.post(
            cmd, json={"command": "pause", "expected_replay_id": replay_id}, headers=first
        ).json()
        assert paused["state"] == "paused"
        assert not simulator.work_once()
        new = client.post(
            cmd, json={"command": "replay", "expected_replay_id": replay_id}, headers=first
        ).json()
        assert new["replay_id"] != replay_id and new["cursor"] == 0
        assert client.get(detail, headers=first).status_code == 200
        assert client.post(cmd, json={"command": "replay"}, headers=first).status_code == 409
