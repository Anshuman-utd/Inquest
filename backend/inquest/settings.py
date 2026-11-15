from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INQUEST_")

    database_url: str = "postgresql+psycopg://inquest_api:local_api@localhost:5434/inquest"
    migration_database_url: str = (
        "postgresql+psycopg://inquest_migrator:local_migrator@localhost:5434/inquest"
    )
    scorer_directory: Path = Path("models/scorer")
    tool_database_url: str = "postgresql+psycopg://inquest_tool:local_tool@localhost:5434/inquest"
    replay_alerts_file: Path = Path("fixtures/replay_alerts.json")
    recordings_file: Path = Path("fixtures/recorded_investigations.json")
    policy_directory: Path = Path("policies")
    ip_hash_secret: SecretStr | None = None
    llm_provider: Literal["groq", "gemini"] = "groq"
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    provider_cache: Path = Path(".cache/inquest/responses.sqlite")
    global_daily_tokens: int = Field(default=100_000, ge=1, le=200_000)
    workspace_daily_investigations: int = Field(default=8, ge=1)
    investigate_per_ip_minute: int = Field(default=10, ge=1)
    evaluation_database_url: str = (
        "postgresql+psycopg://inquest_eval:local_eval@localhost:5434/inquest"
    )
    evaluation_reports_directory: Path = Path("fixtures/evaluations")

    web_origin: str = "http://localhost:5173"
    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    signup_per_ip_minute: int = Field(default=8, ge=1)

    @field_validator("web_origin")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
            or value != f"{url.scheme}://{url.netloc}"
            or (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
        ):
            raise ValueError("Use an HTTPS origin or a loopback HTTP origin without a path")
        return value
