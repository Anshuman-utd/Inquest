from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

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
app = FastAPI(title="Inquest", version="0.2.0")
app.include_router(scoring_router(engine, scorer))


@app.get("/health", tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", tags=["operations"])
def ready() -> HealthResponse:
    try:
        with engine.connect() as connection:
            ready_dataset = connection.execute(
                text("SELECT 1 FROM fixture.datasets WHERE id = :dataset"),
                {"dataset": scorer.manifest.training_dataset_id},
            ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if ready_dataset is None:
        raise HTTPException(status_code=503, detail="Default scoring fixture unavailable")
    return HealthResponse()
