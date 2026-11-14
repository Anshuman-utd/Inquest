from typing import NoReturn

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from inquest.main import app, engine


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> NoReturn:
        raise OperationalError(None, None, OSError("database unavailable"))

    monkeypatch.setattr(engine, "connect", unavailable)
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_scorer_contract_and_missing_transaction() -> None:
    import os

    if os.getenv("INQUEST_TEST_POSTGRES") != "1":
        pytest.skip("requires seeded Postgres")
    with TestClient(app) as client:
        metadata = client.get("/api/v1/scorer").json()
        dataset = metadata["demo_dataset_id"]
        url = f"/api/v1/datasets/{dataset}/transactions"
        response = client.get(f"{url}/150/score")
        missing = client.get(f"{url}/9223372036854775807/score")
        invalid = client.get(f"{url}/0/score")

    assert response.status_code == 200
    score = response.json()
    assert score["model_version"] == metadata["model_version"]
    assert score["feature_version"] == metadata["feature_version"]
    assert score["flagged"] == (score["fraud_probability"] >= metadata["threshold"])
    assert score["contribution_space"] == "raw_margin"
    assert len(score["top_contributions"]) == 5
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_evaluation_api_returns_versioned_public_metrics() -> None:
    with TestClient(app) as client:
        outcome = client.get("/api/v1/evaluations")
        assert outcome.status_code == 200
        assert outcome.json()["schema_version"] == 1
        assert isinstance(outcome.json()["reports"], list)
