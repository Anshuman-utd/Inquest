from hashlib import sha256
from math import exp, isfinite
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

import lightgbm as lgb
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from inquest.scoring.features import FEATURE_NAMES, FEATURE_VERSION

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str
    feature_version: str
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    training_dataset_id: str
    model_sha256: str
    threshold: Probability
    calibration_slope: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    calibration_intercept: Annotated[float, Field(allow_inf_nan=False)]


class Contribution(BaseModel):
    feature: str
    value: float | None
    raw_margin_delta: float


class Score(BaseModel):
    model_version: str
    feature_version: str
    fraud_probability: Probability
    threshold: Probability
    flagged: bool
    raw_margin: float
    base_margin: float
    contribution_space: Literal["raw_margin"] = "raw_margin"
    top_contributions: list[Contribution]


def calibrated_probability(margin: float, slope: float, intercept: float) -> float:
    value = margin * slope + intercept
    if value >= 0:
        return 1 / (1 + exp(-value))
    scaled = exp(value)
    return scaled / (1 + scaled)


class Scorer:
    def __init__(self, directory: Path) -> None:
        self.manifest = ModelManifest.model_validate_json((directory / "manifest.json").read_text())
        model = (directory / "lightgbm.txt").read_bytes()
        if sha256(model).hexdigest() != self.manifest.model_sha256:
            raise ValueError("model artifact digest mismatch")
        if self.manifest.feature_version != FEATURE_VERSION:
            raise ValueError("model feature version does not match serving features")
        self._prediction_lock = Lock()
        self.booster = lgb.Booster(model_str=model.decode())
        if tuple(self.booster.feature_name()) != FEATURE_NAMES:
            raise ValueError("model feature order does not match serving features")

    def predict(self, features: tuple[float, ...]) -> Score:
        row = np.asarray([features], dtype=np.float64)
        manifest = self.manifest
        with self._prediction_lock:
            raw = float(self.booster.predict(row, raw_score=True, num_threads=1)[0])
            explanations = self.booster.predict(row, pred_contrib=True, num_threads=1)[0]
        probability = calibrated_probability(
            raw, manifest.calibration_slope, manifest.calibration_intercept
        )
        ranked = sorted(range(len(features)), key=lambda index: -abs(explanations[index]))[:5]
        return Score(
            model_version=manifest.model_version,
            feature_version=manifest.feature_version,
            fraud_probability=probability,
            threshold=manifest.threshold,
            flagged=probability >= manifest.threshold,
            raw_margin=raw,
            base_margin=float(explanations[-1]),
            top_contributions=[
                Contribution(
                    feature=FEATURE_NAMES[index],
                    value=features[index] if isfinite(features[index]) else None,
                    raw_margin_delta=float(explanations[index]),
                )
                for index in ranked
            ],
        )
