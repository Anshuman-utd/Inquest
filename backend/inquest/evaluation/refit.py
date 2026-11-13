import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from lightgbm import Booster

from inquest.evaluation.thresholds import OperatingPoint, best_under_capacity, sweep_thresholds
from inquest.evaluation.train import (
    MAX_ALERTS_PER_1000,
    MIN_RECALL,
    Cohort,
    diagnostics,
    fit_booster,
    fit_calibrator,
    probabilities,
)
from inquest.scoring.features import FEATURE_VERSION, chronological_features
from inquest.scoring.model import ModelManifest, Scorer
from inquest.synthetic.generator import GENERATOR_VERSION, generate
from inquest.synthetic.models import GeneratorConfig

BASE_CONFIG = Path("fixtures/india.json")
# Independent worlds use disjoint seeds. Fresh test worlds are generated after selection.
FIT_SEEDS = (1729, 2101, 2102)
CALIBRATION_SEED = 2103
VALIDATION_SEED = 2104
TEST_SEED = 2105
SHIFT_SEED = 2106
WARMUP_DAYS = 30
ALERT_BUDGETS = (5, 10, 15, 20, 25, 30, 40, 50, 75, 100)


@dataclass(frozen=True)
class ValidationCandidate:
    name: str
    booster: Booster
    calibration: tuple[float, float]
    best: OperatingPoint
    sweep: list[OperatingPoint]


def cohort(config: GeneratorConfig, seed: int, *, shifted: bool = False) -> Cohort:
    overrides: dict[str, Any] = {"seed": seed}
    if shifted:
        overrides.update(
            {
                "attempts_per_customer_week": config.attempts_per_customer_week * 1.2,
                "amounts": tuple(
                    amount.model_copy(update={"median_minor": round(amount.median_minor * 1.15)})
                    for amount in config.amounts
                ),
            }
        )
    world = generate(GeneratorConfig.model_validate({**config.model_dump(), **overrides}))
    cutoff = world.config.start + timedelta(days=WARMUP_DAYS)
    warmup_episodes = {
        truth.episode_id
        for payment, truth in zip(world.transactions, world.truth, strict=True)
        if payment.occurred_at < cutoff and truth.episode_id is not None
    }
    labels = tuple(
        truth
        for payment, truth in zip(world.transactions, world.truth, strict=True)
        if payment.occurred_at >= cutoff and truth.episode_id not in warmup_episodes
    )
    features = list(chronological_features(world, {label.source_sequence for label in labels}))
    return Cohort(np.asarray(features, dtype=np.float64), labels)


def describe(data: Cohort) -> dict[str, Any]:
    return {
        "attempts": len(data.truth),
        "fraud": int(data.labels.sum()),
        "fraud_by_scenario": dict(
            Counter(label.scenario for label in data.truth if label.is_fraud)
        ),
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def refit(output: Path, *, validation_only: bool) -> None:
    base = GeneratorConfig.model_validate_json(BASE_CONFIG.read_text())
    # Fit on earlier months. Independent calibration/validation/test worlds use later windows.
    fit_config = base.model_copy(update={"days": 150})
    comparison_config = base.model_copy(
        update={
            "start": base.start.replace(month=6, day=1),
            "days": 150,
            "customer_count": 650,
            "merchant_count": 160,
        }
    )
    fit_sets = [cohort(fit_config, seed) for seed in FIT_SEEDS]
    training = Cohort(
        np.concatenate([data.features for data in fit_sets]),
        tuple(label for data in fit_sets for label in data.truth),
    )
    calibration = cohort(comparison_config, CALIBRATION_SEED)
    validation = cohort(comparison_config, VALIDATION_SEED)
    candidates = []
    for name, weight in (("unweighted", 1.0), ("weighted_10", 10.0), ("weighted_30", 30.0)):
        booster = fit_booster(training, positive_weight=weight)
        parameters = fit_calibrator(booster, calibration)
        points = sweep_thresholds(validation.labels, probabilities(booster, validation, parameters))
        best = best_under_capacity(points, MAX_ALERTS_PER_1000)
        candidates.append(ValidationCandidate(name, booster, parameters, best, points))
    chosen = max(candidates, key=lambda item: (item.best.caught, -item.best.alerts))
    summary = {
        "fit": describe(training),
        "calibration": describe(calibration),
        "validation": describe(validation),
        "selected": chosen.name,
        "thresholds_checked": {item.name: len(item.sweep) for item in candidates},
        "validation_candidates": {item.name: item.best.as_dict() for item in candidates},
        "validation_sweep": {
            str(budget): best_under_capacity(chosen.sweep, budget).as_dict()
            for budget in ALERT_BUDGETS
        },
        "validation_target_met": chosen.best.recall >= MIN_RECALL,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "validation.json", summary)
    write_json(output / "all_thresholds.json", [point.as_dict() for point in chosen.sweep])
    if validation_only:
        return

    model = chosen.booster.model_to_string().encode()
    model_hash = sha256(model).hexdigest()
    identity = sha256(
        json.dumps(
            [FEATURE_VERSION, model_hash, chosen.best.threshold, chosen.calibration]
        ).encode()
    ).hexdigest()
    demo = generate(base)
    demo_hash = sha256(demo.model_dump_json().encode()).hexdigest()
    manifest = ModelManifest(
        model_version=f"lgbm-{identity[:16]}",
        feature_version=FEATURE_VERSION,
        currency=base.currency,
        training_dataset_id=f"v{GENERATOR_VERSION}-{demo_hash}",
        model_sha256=model_hash,
        threshold=chosen.best.threshold,
        calibration_slope=chosen.calibration[0],
        calibration_intercept=chosen.calibration[1],
    )
    (output / "lightgbm.txt").write_bytes(model)
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    scorer = Scorer(output)
    test_config = comparison_config.model_copy(update={"start": base.start.replace(month=11)})
    for name, seed, shifted in (("test", TEST_SEED, False), ("shift_test", SHIFT_SEED, True)):
        data = cohort(test_config, seed, shifted=shifted)
        scores = probabilities(scorer.booster, data, chosen.calibration)
        summary[name] = diagnostics(data, scores, manifest.threshold)
    write_json(output / "evaluation.json", {**summary, "manifest": manifest.model_dump()})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select a scorer with an exhaustive validation sweep"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/scorer-refit"))
    parser.add_argument("--validation-only", action="store_true")
    args = parser.parse_args()
    refit(args.output, validation_only=args.validation_only)


if __name__ == "__main__":
    main()
