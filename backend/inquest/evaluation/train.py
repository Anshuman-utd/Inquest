import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import lightgbm as lgb
import numpy as np
from numpy.typing import NDArray
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from inquest.scoring.features import FEATURE_NAMES, FEATURE_VERSION, chronological_features
from inquest.scoring.model import ModelManifest, calibrated_probability
from inquest.synthetic.generator import GENERATOR_VERSION, SCENARIO_LENGTHS, generate
from inquest.synthetic.models import GeneratorConfig, Truth, World

Split = Literal["warmup", "train", "calibration", "validation", "test"]
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
MIN_RECALL = 0.9
MAX_ALERTS_PER_1000 = 30


@dataclass(frozen=True)
class Cohort:
    features: FloatArray
    truth: tuple[Truth, ...]

    @property
    def labels(self) -> IntArray:
        return np.asarray([label.is_fraud for label in self.truth], dtype=np.int64)


def assign_split(day: int, days: int) -> Split:
    boundaries: tuple[tuple[float, Split], ...] = (
        (1 / 6, "warmup"),
        (0.6, "train"),
        (2 / 3, "calibration"),
        (5 / 6, "validation"),
    )
    for fraction, split in boundaries:
        if day < round(days * fraction):
            return split
    return "test"


def make_cohorts(world: World, selected: set[Split]) -> tuple[dict[Split, Cohort], int]:
    splits = [
        assign_split((transaction.occurred_at - world.config.start).days, world.config.days)
        for transaction in world.transactions
    ]
    episode_splits: dict[str, set[Split]] = defaultdict(set)
    for label, split in zip(world.truth, splits, strict=True):
        if label.episode_id is not None:
            episode_splits[label.episode_id].add(split)
    spanning = {episode for episode, windows in episode_splits.items() if len(windows) > 1}
    features: dict[Split, list[tuple[float, ...]]] = defaultdict(list)
    labels: dict[Split, list[Truth]] = defaultdict(list)
    for values, label, split in zip(
        chronological_features(world), world.truth, splits, strict=True
    ):
        if split in selected and label.episode_id not in spanning:
            features[split].append(values)
            labels[split].append(label)
    return {
        split: Cohort(np.asarray(features[split], dtype=np.float64), tuple(labels[split]))
        for split in sorted(selected)
    }, len(spanning)


def binary_metrics(labels: IntArray, scores: FloatArray, threshold: float) -> dict[str, Any]:
    flagged = scores >= threshold
    positive = labels == 1
    tp = int(np.count_nonzero(flagged & positive))
    fp = int(np.count_nonzero(flagged & ~positive))
    fn = int(np.count_nonzero(~flagged & positive))
    tn = len(labels) - tp - fp - fn
    return {
        "attempts": len(labels),
        "fraud": tp + fn,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "average_precision": float(average_precision_score(labels, scores)) if tp + fn else None,
        "alerts_per_1000": 1000 * (tp + fp) / len(labels),
    }


def operating_point(labels: IntArray, scores: FloatArray) -> float | None:
    _, recall, thresholds = precision_recall_curve(labels, scores)
    eligible = thresholds[recall[:-1] >= MIN_RECALL]
    if len(eligible) == 0:
        return None
    threshold = float(eligible[-1])
    if np.count_nonzero(scores >= threshold) * 1000 <= MAX_ALERTS_PER_1000 * len(labels):
        return threshold
    return None


def capacity_point(scores: FloatArray) -> float:
    thresholds, counts = np.unique(scores, return_counts=True)
    feasible = np.cumsum(counts[::-1]) * 1000 <= MAX_ALERTS_PER_1000 * len(scores)
    eligible = thresholds[::-1][feasible]
    return float(eligible[-1]) if len(eligible) else float(np.nextafter(scores.max(), np.inf))


def fit_booster(cohort: Cohort, *, positive_weight: float) -> Any:
    data = lgb.Dataset(cohort.features, label=cohort.labels, feature_name=list(FEATURE_NAMES))
    return lgb.train(
        {
            "objective": "binary",
            "verbosity": -1,
            "seed": 1729,
            "num_threads": 1,
            "deterministic": True,
            "force_col_wise": True,
            "num_leaves": 15,
            "max_depth": 4,
            "min_data_in_leaf": 15,
            "learning_rate": 0.06,
            "lambda_l2": 2,
            "scale_pos_weight": positive_weight,
        },
        data,
        num_boost_round=140,
    )


def fit_calibrator(booster: Any, cohort: Cohort) -> tuple[float, float]:
    margin = booster.predict(cohort.features, raw_score=True, num_threads=1)
    fit = LogisticRegression(C=10, solver="lbfgs").fit(margin.reshape(-1, 1), cohort.labels)
    slope, intercept = float(fit.coef_[0, 0]), float(fit.intercept_[0])
    if slope <= 0:
        raise ValueError("calibration did not preserve ranking")
    return slope, intercept


def probabilities(booster: Any, cohort: Cohort, calibration: tuple[float, float]) -> FloatArray:
    margins = booster.predict(cohort.features, raw_score=True, num_threads=1)
    return np.asarray([calibrated_probability(float(raw), *calibration) for raw in margins])


def diagnostics(cohort: Cohort, scores: FloatArray, threshold: float) -> dict[str, Any]:
    result = binary_metrics(cohort.labels, scores, threshold)
    fraud, caught, lookalikes, lookalike_alerts = (Counter[str]() for _ in range(4))
    fraud_episodes = {label.episode_id for label in cohort.truth if label.is_fraud}
    for label, score in zip(cohort.truth, scores, strict=True):
        if label.scenario is None:
            continue
        if label.is_fraud:
            fraud[label.scenario] += 1
            caught[label.scenario] += int(score >= threshold)
        if label.episode_id not in fraud_episodes:
            lookalikes[label.scenario] += 1
            lookalike_alerts[label.scenario] += int(score >= threshold)
    result["scenarios"] = {
        name: {
            "fraud": fraud[name],
            "caught": caught[name],
            "recall": caught[name] / fraud[name] if fraud[name] else None,
            "legitimate_lookalikes": lookalikes[name],
            "lookalike_alerts": lookalike_alerts[name],
        }
        for name in sorted(SCENARIO_LENGTHS)
    }
    result["brier"] = float(brier_score_loss(cohort.labels, scores))
    precision, recall, _ = precision_recall_curve(cohort.labels, scores)
    result["pr_curve"] = [
        {"recall": float(r), "precision": float(p)} for p, r in zip(precision, recall, strict=True)
    ]
    result["reliability"] = []
    for low, high in zip(
        (0, 0.01, 0.05, 0.1, 0.25, 0.5), (0.01, 0.05, 0.1, 0.25, 0.5, 1), strict=True
    ):
        group = (scores >= low) & ((scores < high) if high < 1 else (scores <= high))
        if np.any(group):
            result["reliability"].append(
                {
                    "range": [low, high],
                    "attempts": int(group.sum()),
                    "mean_probability": float(scores[group].mean()),
                    "observed_fraud_rate": float(cohort.labels[group].mean()),
                }
            )
    return result


def train(config: GeneratorConfig, output: Path, *, validation_only: bool) -> bool:
    world = generate(config)
    cohorts, spanning = make_cohorts(world, {"train", "calibration", "validation"})
    training, calibration, validation = (
        cohorts[key] for key in ("train", "calibration", "validation")
    )
    for split_name, cohort in cohorts.items():
        if len(np.unique(cohort.labels)) < 2:
            raise ValueError(f"{split_name} needs both classes")
    positive_weight = min(
        30.0, float(np.count_nonzero(training.labels == 0) / training.labels.sum())
    )
    linear = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        LogisticRegression(max_iter=1000),
    ).fit(training.features, training.labels)
    candidates: dict[str, dict[str, Any]] = {}
    linear_scores = linear.predict_proba(validation.features)[:, 1]
    candidates["logistic"] = binary_metrics(
        validation.labels, linear_scores, capacity_point(linear_scores)
    )
    eligible: list[tuple[float, str, Any, tuple[float, float], float]] = []
    for name, weight in (("lightgbm_unweighted", 1.0), ("lightgbm_weighted", positive_weight)):
        booster = fit_booster(training, positive_weight=weight)
        parameters = fit_calibrator(booster, calibration)
        scores = probabilities(booster, validation, parameters)
        threshold = operating_point(validation.labels, scores)
        candidates[name] = {
            **binary_metrics(validation.labels, scores, capacity_point(scores)),
            "eligible_threshold": threshold,
            "positive_weight": weight,
        }
        if threshold is not None:
            eligible.append(
                (
                    float(average_precision_score(validation.labels, scores)),
                    name,
                    booster,
                    parameters,
                    threshold,
                )
            )
    summary = {
        "split_counts": {
            name: {"attempts": len(cohort.truth), "fraud": int(cohort.labels.sum())}
            for name, cohort in cohorts.items()
        },
        "spanning_episodes_excluded": spanning,
        "validation_candidates_at_capacity": candidates,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    if not eligible:
        return False
    if validation_only:
        return True

    _, name, booster, parameters, threshold = max(eligible, key=lambda item: item[0])
    checksum = hashlib.sha256(world.model_dump_json().encode()).hexdigest()
    model = booster.model_to_string().encode()
    model_hash = hashlib.sha256(model).hexdigest()
    identity = hashlib.sha256(
        json.dumps([FEATURE_VERSION, checksum, model_hash, threshold, parameters]).encode()
    ).hexdigest()
    manifest = ModelManifest(
        model_version=f"lgbm-{identity[:16]}",
        feature_version=FEATURE_VERSION,
        training_dataset_id=f"v{GENERATOR_VERSION}-{checksum}",
        model_sha256=model_hash,
        threshold=threshold,
        calibration_slope=parameters[0],
        calibration_intercept=parameters[1],
    )
    (output / "lightgbm.txt").write_bytes(model)
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")

    tests, _ = make_cohorts(world, {"test"})
    shift_config = config.model_copy(
        update={
            "seed": config.seed + 1,
            "attempts_per_customer_week": min(12, config.attempts_per_customer_week * 1.2),
            "amounts": tuple(
                item.model_copy(update={"median_minor": round(item.median_minor * 1.15)})
                for item in config.amounts
            ),
        }
    )
    shifted, shift_spanning = make_cohorts(generate(shift_config), {"test"})
    summary.update(
        {
            "model": name,
            "manifest": manifest.model_dump(),
            "validation": diagnostics(
                validation, probabilities(booster, validation, parameters), threshold
            ),
            "test": diagnostics(
                tests["test"], probabilities(booster, tests["test"], parameters), threshold
            ),
            "shift_test": diagnostics(
                shifted["test"], probabilities(booster, shifted["test"], parameters), threshold
            ),
            "shift_spanning_episodes_excluded": shift_spanning,
        }
    )
    (output / "evaluation.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate Inquest's fraud scorer")
    parser.add_argument("--config", type=Path, default=Path("fixtures/india.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/scorer"))
    parser.add_argument("--validation-only", action="store_true")
    args = parser.parse_args()
    config = GeneratorConfig.model_validate_json(args.config.read_text())
    if not train(config, args.output, validation_only=args.validation_only):
        raise SystemExit(
            "Validation target unmet. See validation.json. The test window was not evaluated."
        )


if __name__ == "__main__":
    main()
