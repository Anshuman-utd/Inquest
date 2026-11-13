from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INQUEST_")

    database_url: str = "postgresql+psycopg://inquest_api:local_api@localhost:5434/inquest"
    migration_database_url: str = (
        "postgresql+psycopg://inquest_migrator:local_migrator@localhost:5434/inquest"
    )
    scorer_directory: Path = Path("models/scorer")
