from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INQUEST_")

    database_url: str = "postgresql+psycopg://inquest_api:local_api@localhost:5434/inquest"
    migration_database_url: str = (
        "postgresql+psycopg://inquest_migrator:local_migrator@localhost:5434/inquest"
    )
    scorer_directory: Path = Path("models/scorer")
    tool_database_url: str = "postgresql+psycopg://inquest_tool:local_tool@localhost:5434/inquest"
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
