from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from inquest.settings import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


engine = create_engine(
    Settings().database_url,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=0,
    pool_timeout=3,
    connect_args={"connect_timeout": 3},
)
app = FastAPI(title="Inquest", version="0.1.0")


@app.get("/health", tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", tags=["operations"])
def ready() -> HealthResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM fixture.datasets LIMIT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return HealthResponse()
