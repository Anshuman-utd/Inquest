from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from inquest.evaluation.publish_scorer import ScorerEvaluation

Arm = Literal["ml_only", "full", "no_tools", "no_policy", "no_self_check"]


class PublishedFields(BaseModel):
    model_config = ConfigDict(extra="allow")


class CohortConfig(PublishedFields):
    start: datetime
    days: int


class Cohort(PublishedFields):
    name: str
    config: CohortConfig
    attempts: int
    fraud: int
    alerted: int
    alerted_fraud: int


class Latency(BaseModel):
    cases: int
    p50_seconds: float | None
    p95_seconds: float | None


class ArmResult(PublishedFields):
    sample_size: int
    sample_fraud: int
    sample_true_releases: int
    sample_false_releases: int
    legit_alerts_cleared: float | None
    alert_fraud_retained: float | None
    end_to_end_fraud_retained: float | None
    grounded_sample: int
    grounding_denominator: int
    failure_codes: dict[str, int]
    accounted_tokens: int
    live_latency: Latency
    cache_only_latency: Latency


class RunProvenance(PublishedFields):
    provider: str
    cache_only: bool


class EvaluationReport(BaseModel):
    schema_version: Literal[1]
    revision: str
    run_ids: dict[Arm, UUID]
    cohort: Cohort
    arms: dict[Arm, ArmResult]
    provenance: dict[Arm, RunProvenance]


class PublishedEvaluations(BaseModel):
    schema_version: Literal[1] = 1
    reports: list[EvaluationReport]
    scorer: ScorerEvaluation | None


def evaluation_router(directory: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["evaluation"])
    reports = [
        EvaluationReport.model_validate_json(path.read_text())
        for path in sorted(directory.glob("phase5-*.json"))
    ]

    source = directory / "scorer.json"
    scorer = ScorerEvaluation.model_validate_json(source.read_text()) if source.exists() else None

    @router.get("/evaluations")
    def evaluations() -> PublishedEvaluations:
        return PublishedEvaluations(reports=reports, scorer=scorer)

    return router
