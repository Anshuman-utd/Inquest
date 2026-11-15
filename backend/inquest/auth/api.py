from collections.abc import Callable
from hashlib import sha256
from hmac import compare_digest, digest
from secrets import token_urlsafe
from typing import Annotated, Literal
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import Engine, text

from inquest.auth.providers import Provider, ProviderName
from inquest.investigation.runtime import RateLimited, consume_ip
from inquest.settings import Settings

SESSION_COOKIE = "inquest_session"
SESSION_AGE = 3600
headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
bearer = HTTPBearer(auto_error=False)
cookie = APIKeyCookie(name=SESSION_COOKIE, auto_error=False)
Identity = tuple[UUID, UUID]
Actor = Callable[..., Identity]


def hash_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def client_ip_hash(request: Request, key: bytes) -> str:
    return digest(
        key, (request.client.host if request.client else "unknown").encode(), "sha256"
    ).hex()


def require_origin(request: Request, origin: str) -> None:
    if request.headers.get("origin") != origin:
        raise HTTPException(status_code=403, detail="Untrusted request origin")


def authenticate(lookup: Callable[[str], Identity | None], origin: str) -> Actor:
    def actor(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        session: Annotated[str | None, Depends(cookie)],
    ) -> Identity:
        if credentials:
            session = credentials.credentials
        elif session and request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_origin(request, origin)
        identity = lookup(hash_token(session)) if session and 32 <= len(session) <= 256 else None
        if identity is None:
            raise HTTPException(status_code=401, detail="Analyst session required")
        return identity

    return actor


class Session(BaseModel):
    workspace_id: UUID
    analyst_id: UUID


class AuthOptions(BaseModel):
    github: bool
    google: bool


def auth_router(engine: Engine, settings: Settings, actor: Actor, ip_key: bytes) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
    origin = settings.web_origin
    secure = origin.startswith("https://")
    providers: dict[ProviderName, Provider] = {}
    if settings.github_client_id and settings.github_client_secret:
        providers["github"] = Provider(
            "github", settings.github_client_id, settings.github_client_secret, origin
        )
    if settings.google_client_id and settings.google_client_secret:
        providers["google"] = Provider(
            "google", settings.google_client_id, settings.google_client_secret, origin
        )

    @router.get("/providers")
    def options() -> AuthOptions:
        return AuthOptions(github="github" in providers, google="google" in providers)

    @router.post("/{provider}/start", status_code=303, response_class=RedirectResponse)
    def start(
        provider: ProviderName, request: Request, intent: Literal["login", "signup"] = "login"
    ) -> RedirectResponse:
        require_origin(request, origin)
        selected = providers.get(provider)
        if selected is None:
            return RedirectResponse(f"{origin}/{intent}?error=unavailable", 303, headers)
        state = token_urlsafe(32)
        nonce = token_urlsafe(32)
        verifier = token_urlsafe(48)
        try:
            with engine.begin() as connection:
                consume_ip(
                    connection,
                    client_ip_hash(request, ip_key),
                    settings.signup_per_ip_minute,
                    action="signup",
                )
                connection.execute(
                    text("DELETE FROM operations.oauth_attempts WHERE expires_at <= now()")
                )
                connection.execute(
                    text("""
                        INSERT INTO operations.oauth_attempts
                            (state_hash, provider, nonce, verifier, return_to)
                        VALUES (:state, :provider, :nonce, :verifier, :return_to)
                    """),
                    {
                        "state": hash_token(state),
                        "provider": provider,
                        "nonce": nonce,
                        "verifier": verifier,
                        "return_to": f"/{intent}",
                    },
                )
        except RateLimited:
            return RedirectResponse(f"{origin}/{intent}?error=rate", 303, headers)
        response = RedirectResponse(
            selected.authorization_url(state, verifier, nonce), 303, headers
        )
        response.set_cookie(
            f"inquest_oauth_{provider}",
            state,
            max_age=600,
            httponly=True,
            secure=secure,
            samesite="lax",
        )
        return response

    @router.get("/{provider}/callback", status_code=303, response_class=RedirectResponse)
    def callback(
        provider: ProviderName,
        request: Request,
        state: str = "",
        code: str = "",
    ) -> RedirectResponse:
        selected = providers.get(provider)
        cookie_name = f"inquest_oauth_{provider}"
        browser_state = request.cookies.get(cookie_name, "")
        if (
            selected is None
            or len(state) != 43
            or not compare_digest(state.encode(), browser_state.encode())
        ):
            return RedirectResponse(f"{origin}/login?error=oauth", 303, headers)
        with engine.begin() as connection:
            attempt = connection.execute(
                text("""
                    DELETE FROM operations.oauth_attempts
                    WHERE state_hash = :state AND provider = :provider AND expires_at > now()
                    RETURNING verifier, nonce, return_to
                """),
                {"state": hash_token(state), "provider": provider},
            ).one_or_none()
        response = RedirectResponse(
            f"{origin}{attempt.return_to if attempt else '/login'}?error=oauth", 303, headers
        )
        response.delete_cookie(cookie_name, httponly=True, secure=secure, samesite="lax")
        if attempt is None or not 1 <= len(code) <= 2048:
            return response
        try:
            subject = selected.subject(code, attempt.verifier, attempt.nonce)
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, TypeError, ValueError):
            return response
        token = token_urlsafe(32)
        old_token = request.cookies.get(SESSION_COOKIE)
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM operations.analyst_sessions WHERE expires_at <= now()")
            )
            if old_token and 32 <= len(old_token) <= 256:
                connection.execute(
                    text("DELETE FROM operations.analyst_sessions WHERE token_sha256 = :token"),
                    {"token": hash_token(old_token)},
                )
            connection.execute(
                text("""
                    INSERT INTO operations.analyst_sessions
                    SELECT :token, workspace_id, analyst_id, now() + :age * interval '1 second'
                    FROM operations.provision_oauth(:provider, :subject)
                """),
                {
                    "token": hash_token(token),
                    "age": SESSION_AGE,
                    "provider": provider,
                    "subject": subject,
                },
            )
        response.headers["location"] = f"{origin}/"
        response.set_cookie(
            SESSION_COOKIE, token, max_age=SESSION_AGE, httponly=True, secure=secure, samesite="lax"
        )
        return response

    @router.get("/session")
    def session(response: Response, identity: Annotated[Identity, Depends(actor)]) -> Session:
        response.headers["Cache-Control"] = "no-store"
        return Session(workspace_id=identity[0], analyst_id=identity[1])

    @router.post("/logout", status_code=204)
    def logout(request: Request) -> Response:
        require_origin(request, origin)
        token = request.cookies.get(SESSION_COOKIE)
        if token and 32 <= len(token) <= 256:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM operations.analyst_sessions WHERE token_sha256 = :token"),
                    {"token": hash_token(token)},
                )
        response = Response(status_code=204, headers=headers)
        response.delete_cookie(SESSION_COOKIE, httponly=True, secure=secure, samesite="lax")
        return response

    return router
