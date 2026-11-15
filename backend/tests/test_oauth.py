import os
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from inquest.auth.api import SESSION_COOKIE, auth_router, authenticate
from inquest.auth.providers import Provider
from inquest.main import investigations
from inquest.settings import Settings


def test_google_checks_nonce_audience_and_signature() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    provider = Provider("google", "client", SecretStr("secret"), "http://localhost:5173")
    now = datetime.now(UTC)
    claims = {
        "aud": "client",
        "nonce": "expected",
        "iat": now,
        "iss": "https://accounts.google.com",
        "sub": "stable-subject",
        "exp": now + timedelta(minutes=1),
    }
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"keys": [dict(jwk) | {"kid": "test"}]})
    )
    with httpx.Client(transport=transport) as client:
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
        assert provider._google_subject(client, token, "expected") == "stable-subject"
        with pytest.raises(ValueError, match="nonce"):
            provider._google_subject(client, token, "wrong")
        for extra in ({"aud": "wrong"}, {"exp": now - timedelta(seconds=1)}):
            bad = jwt.encode(claims | extra, key, algorithm="RS256", headers={"kid": "test"})
            with pytest.raises(jwt.InvalidTokenError):
                provider._google_subject(client, bad, "expected")
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        bad = jwt.encode(claims, wrong_key, algorithm="RS256", headers={"kid": "test"})
        with pytest.raises(jwt.InvalidSignatureError):
            provider._google_subject(client, bad, "expected")


@pytest.mark.skipif(os.getenv("INQUEST_TEST_POSTGRES") != "1", reason="requires migrated Postgres")
def test_both_oauth_providers_create_and_restore_isolated_workspaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        github_client_id="github",
        github_client_secret=SecretStr("test-github"),
        google_client_id="google",
        google_client_secret=SecretStr("test-google"),
        signup_per_ip_minute=3,
    )
    subject = str(uuid4())
    monkeypatch.setattr(Provider, "subject", lambda *_: subject)
    api = create_engine(settings.database_url)
    owner = create_engine(settings.migration_database_url)
    app = FastAPI()
    app.include_router(
        auth_router(api, settings, authenticate(investigations.auth, settings.web_origin), b"key")
    )
    origin = {"Origin": settings.web_origin}
    identities = []
    try:
        with TestClient(app, base_url=settings.web_origin, follow_redirects=False) as client:
            assert client.get("/api/v1/auth/session").status_code == 401
            for provider in ("github", "google", "github"):
                start = f"/api/v1/auth/{provider}/start"
                callback = f"/api/v1/auth/{provider}/callback"
                assert (
                    client.post(start, headers={"Origin": "https://other.example"}).status_code
                    == 403
                )
                response = client.post(start + "?intent=signup", headers=origin)
                params = parse_qs(urlparse(response.headers["location"]).query)
                assert params["code_challenge_method"] == ["S256"]
                assert bool(params.get("nonce")) == (provider == "google")
                state = params["state"][0]
                wrong = client.get(callback, params={"state": "wrong", "code": "test"})
                assert wrong.headers["location"].endswith("?error=oauth")
                done = client.get(callback, params={"state": state, "code": "test"})
                assert done.headers["location"] == f"{settings.web_origin}/"
                assert any(
                    SESSION_COOKIE in header and "HttpOnly" in header
                    for header in done.headers.get_list("set-cookie")
                )
                identity = client.get("/api/v1/auth/session").json()
                identities.append(identity)
                token = client.cookies[SESSION_COOKIE]
                assert client.post("/api/v1/auth/logout", headers=origin).status_code == 204
                assert (
                    client.get(
                        "/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"}
                    ).status_code
                    == 401
                )
                replay = client.get(callback, params={"state": state, "code": "test"})
                assert replay.headers["location"].endswith("?error=oauth")
            assert identities[0] == identities[2]
            assert identities[0]["workspace_id"] != identities[1]["workspace_id"]
            rate = client.post("/api/v1/auth/github/start", headers=origin)
            assert rate.headers["location"].endswith("?error=rate")
    finally:
        api.dispose()
        with owner.begin() as conn:
            conn.execute(
                text("DELETE FROM operations.oauth_identities WHERE subject = :subject"),
                {"subject": subject},
            )
            for identity in identities[:2]:
                for statement in (
                    "DELETE FROM operations.analyst_sessions WHERE workspace_id = :workspace_id",
                    "DELETE FROM operations.workspace_memberships "
                    "WHERE workspace_id = :workspace_id",
                    "DELETE FROM operations.workspaces WHERE id = :workspace_id",
                    "DELETE FROM operations.analysts WHERE id = :analyst_id",
                ):
                    conn.execute(text(statement), identity)
        owner.dispose()
