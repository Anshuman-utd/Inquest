from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


app = FastAPI(title="Inquest", version="0.1.0")


@app.get("/health", tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()
