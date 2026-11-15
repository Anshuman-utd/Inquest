from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Literal
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import SecretStr

ProviderName = Literal["github", "google"]


@dataclass(frozen=True)
class Provider:
    name: ProviderName
    client_id: str
    secret: SecretStr
    origin: str

    @property
    def callback(self) -> str:
        return f"{self.origin}/api/v1/auth/{self.name}/callback"

    def authorization_url(self, state: str, verifier: str, nonce: str) -> str:
        challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
        payload = {
            "client_id": self.client_id,
            "redirect_uri": self.callback,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self.name == "github":
            endpoint = "https://github.com/login/oauth/authorize"
            payload["scope"] = ""
        else:
            endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
            payload.update(response_type="code", scope="openid", nonce=nonce)
        return f"{endpoint}?{urlencode(payload)}"

    def subject(self, code: str, verifier: str, nonce: str) -> str:
        endpoint = (
            "https://github.com/login/oauth/access_token"
            if self.name == "github"
            else "https://oauth2.googleapis.com/token"
        )
        with httpx.Client(timeout=5, headers={"Accept": "application/json"}) as client:
            response = client.post(
                endpoint,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": self.callback,
                    "code_verifier": verifier,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            tokens = response.json()
            if self.name == "github":
                profile = client.get(
                    "https://api.github.com/user",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                )
                profile.raise_for_status()
                github_id = profile.json()["id"]
                if type(github_id) is not int or github_id < 1:
                    raise ValueError("Invalid GitHub subject")
                return str(github_id)
            return self._google_subject(client, tokens["id_token"], nonce)

    def _google_subject(self, client: httpx.Client, token: str, nonce: str) -> str:
        response = client.get("https://www.googleapis.com/oauth2/v3/certs")
        response.raise_for_status()
        key = jwt.PyJWKSet.from_dict(response.json())[jwt.get_unverified_header(token)["kid"]]
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self.client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        )
        if claims["aud"] != self.client_id or claims.get("azp", self.client_id) != self.client_id:
            raise ValueError("Invalid Google authorized party")
        if not isinstance(claims["nonce"], str) or not compare_digest(
            claims["nonce"].encode(), nonce.encode()
        ):
            raise ValueError("Invalid Google nonce")
        subject: str = claims["sub"]
        if not 1 <= len(subject) <= 255:
            raise ValueError("Invalid Google subject")
        return subject
