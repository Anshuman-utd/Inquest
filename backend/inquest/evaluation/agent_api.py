from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

Arm = Literal["ml_only", "full", "no_tools", "no_policy", "no_self_check"]


class EvaluationReport(BaseModel):
    schema_version: Literal[1]
    revision: str
    run_ids: dict[Arm, UUID]
    cohort: dict[str, Any]
    arms: dict[Arm, dict[str, Any]]
    provenance: dict[Arm, dict[str, Any]]


class PublishedEvaluations(BaseModel):
    schema_version: Literal[1] = 1
    reports: list[EvaluationReport]


def evaluation_router(directory: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["evaluation"])
    reports = [
        EvaluationReport.model_validate_json(path.read_text())
        for path in sorted(directory.glob("phase5-*.json"))
    ]

    @router.get("/evaluations")
    def evaluations() -> PublishedEvaluations:
        return PublishedEvaluations(reports=reports)

    return router
