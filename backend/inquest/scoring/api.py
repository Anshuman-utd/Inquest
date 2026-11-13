from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from inquest.scoring.model import Score, Scorer
from inquest.scoring.repository import transaction_features

DatasetID = Annotated[str, ApiPath(pattern=r"^v[1-9][0-9]*-[a-f0-9]{64}$", max_length=80)]
SourceSequence = Annotated[int, ApiPath(gt=0, le=2**63 - 1)]


class ScorerInfo(BaseModel):
    model_version: str
    feature_version: str
    threshold: float
    currency: str
    training_dataset_id: str


def scoring_router(engine: Engine, scorer: Scorer) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["scoring"])

    @router.get("/scorer")
    def model_info() -> ScorerInfo:
        manifest = scorer.manifest
        return ScorerInfo(
            model_version=manifest.model_version,
            feature_version=manifest.feature_version,
            threshold=manifest.threshold,
            currency=manifest.currency,
            training_dataset_id=manifest.training_dataset_id,
        )

    @router.get("/datasets/{dataset_id}/transactions/{source_sequence}/score")
    def score_transaction(dataset_id: DatasetID, source_sequence: SourceSequence) -> Score:
        try:
            with engine.connect() as connection:
                features = transaction_features(
                    connection, dataset_id, source_sequence, currency=scorer.manifest.currency
                )
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        if features is None:
            raise HTTPException(status_code=404, detail="Transaction unavailable for scoring")
        return scorer.predict(features)

    return router
