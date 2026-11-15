"""Prepare scorer output for the immutable serving fixture used by the replay simulator."""

import argparse
from hashlib import sha256
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from inquest.scoring.features import chronological_features
from inquest.scoring.model import Score, Scorer, calibrated_probability
from inquest.settings import Settings
from inquest.synthetic.generator import GENERATOR_VERSION, generate
from inquest.synthetic.models import GeneratorConfig


class Alert(BaseModel):
    sequence: int
    score: Score


class ReplayFixture(BaseModel):
    dataset_id: str
    model_sha256: str
    threshold: float
    total: int
    alerts: list[Alert]

    @classmethod
    def read(cls, path: Path, scorer: Scorer) -> "ReplayFixture":
        fixture = cls.model_validate_json(path.read_text())
        manifest = scorer.manifest
        if (
            fixture.dataset_id != manifest.serving_dataset_id
            or fixture.model_sha256 != manifest.model_sha256
            or fixture.threshold != manifest.threshold
        ):
            raise ValueError("Replay fixture does not match the serving fixture and model")
        return fixture


def prepare(config: Path, scorer: Scorer) -> ReplayFixture:
    world = generate(GeneratorConfig.model_validate_json(config.read_text()))
    checksum = sha256(world.model_dump_json().encode()).hexdigest()
    manifest = scorer.manifest
    dataset_id = f"v{GENERATOR_VERSION}-{checksum}"
    if dataset_id != manifest.serving_dataset_id:
        raise ValueError("Generated data does not match the model's serving fixture")
    features = np.asarray(list(chronological_features(world)), dtype=np.float64)
    margins = scorer.booster.predict(features, raw_score=True, num_threads=1)
    alerts = [
        Alert(sequence=payment.source_sequence, score=scorer.predict(tuple(values)))
        for payment, values, margin in zip(world.transactions, features, margins, strict=True)
        if calibrated_probability(
            margin, manifest.calibration_slope, manifest.calibration_intercept
        )
        >= manifest.threshold
    ]
    return ReplayFixture(
        dataset_id=dataset_id,
        model_sha256=manifest.model_sha256,
        threshold=manifest.threshold,
        total=world.transactions[-1].source_sequence,
        alerts=alerts,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("fixtures/india.json"))
    parser.add_argument("--output", type=Path, default=Path("fixtures/replay_alerts.json"))
    args = parser.parse_args()
    fixture = prepare(args.config, Scorer(Settings().scorer_directory))
    args.output.write_text(fixture.model_dump_json() + "\n")
    print(f"Prepared {len(fixture.alerts)} alerts over {fixture.total} attempts.")
