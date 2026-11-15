"""Export a bounded precision-recall series and operating metrics for the console."""

import argparse
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class PRPoint(BaseModel):
    precision: float
    recall: float


class ScenarioMetrics(BaseModel):
    fraud: int
    caught: int
    recall: float | None


class ScorerCohort(BaseModel):
    attempts: int
    fraud: int
    recall: float
    precision: float
    average_precision: float
    alerts_per_1000: float
    scenarios: dict[str, ScenarioMetrics]
    pr_curve: list[PRPoint]


class ScorerEvaluation(BaseModel):
    model_version: str
    threshold: float
    cohorts: dict[Literal["test", "shift_test"], ScorerCohort]


def sample(points: list[dict[str, float]]) -> list[dict[str, float]]:
    # Preserve the best precision in each one-point recall band.
    best: dict[int, dict[str, float]] = {}
    for point in points:
        band = round(point["recall"] * 100)
        if band not in best or point["precision"] > best[band]["precision"]:
            best[band] = point
    return [best[band] for band in sorted(best)]


def publish(source: dict[str, Any]) -> ScorerEvaluation:
    return ScorerEvaluation.model_validate(
        {
            "model_version": source["manifest"]["model_version"],
            "threshold": source["manifest"]["threshold"],
            "cohorts": {
                name: source[name] | {"pr_curve": sample(source[name]["pr_curve"])}
                for name in ("test", "shift_test")
            },
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        publish(json.loads(args.source.read_text())).model_dump_json(indent=2) + "\n"
    )
