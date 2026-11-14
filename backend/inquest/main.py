from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import token_bytes
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from inquest.db.tenant import TenantDatabase
from inquest.evaluation.agent_api import evaluation_router
from inquest.investigation.api import investigation_router, supervise
from inquest.investigation.graph import Steps
from inquest.investigation.policy import PolicyIndex
from inquest.investigation.provider import GroqProvider, ModelGateway, Provider, ResponseCache
from inquest.investigation.replay import Recordings
from inquest.investigation.service import Investigations
from inquest.investigation.tools import InvestigationTools
from inquest.scoring.api import scoring_router
from inquest.scoring.model import Scorer
from inquest.settings import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


settings = Settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=0,
    pool_timeout=3,
    connect_args={"connect_timeout": 3, "options": "-c timezone=UTC -c statement_timeout=5000"},
)
scorer = Scorer(settings.scorer_directory)
reader = create_engine(
    settings.tool_database_url, pool_size=1, max_overflow=0, connect_args={"connect_timeout": 3}
)
tools = InvestigationTools(TenantDatabase(engine), reader, PolicyIndex(settings.policy_directory))


def configured_gateway(config: Settings) -> ModelGateway | None:
    provider: Provider
    if config.llm_provider == "gemini":
        if not config.gemini_api_key:
            raise ValueError("Gemini selection requires INQUEST_GEMINI_API_KEY")
        from inquest.investigation.gemini import GeminiProvider

        provider = GeminiProvider(config.gemini_api_key.get_secret_value())
    elif config.groq_api_key:
        provider = GroqProvider(config.groq_api_key.get_secret_value())
    else:
        return None
    return ModelGateway(provider, ResponseCache(config.provider_cache))


gateway = configured_gateway(settings)
investigations = Investigations(
    engine,
    Steps(
        TenantDatabase(engine),
        tools,
        gateway,
        settings.global_daily_tokens,
        Recordings(settings.recordings_file),
    ),
    settings,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with supervise(investigations):
        yield


app = FastAPI(title="Inquest", version="0.4.0", lifespan=lifespan)
ip_key = (
    settings.ip_hash_secret.get_secret_value().encode()
    if settings.ip_hash_secret
    else token_bytes(32)
)
app.include_router(investigation_router(investigations, ip_key))
app.include_router(scoring_router(engine, scorer))
app.include_router(evaluation_router(settings.evaluation_reports_directory))


@app.get("/health", tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", tags=["operations"])
def ready() -> HealthResponse:
    try:
        with engine.connect() as connection:
            ready_dataset = connection.execute(
                text("SELECT 1 FROM fixture.datasets WHERE id = :dataset"),
                {"dataset": scorer.manifest.serving_dataset_id},
            ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if ready_dataset is None:
        raise HTTPException(status_code=503, detail="Default scoring fixture unavailable")
    return HealthResponse()
