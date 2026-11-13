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
