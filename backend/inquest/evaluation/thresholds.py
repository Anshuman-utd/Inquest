from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class OperatingPoint:
    threshold: float
    alerts: int
    caught: int
    attempts: int
    fraud: int

    @property
    def recall(self) -> float:
        return self.caught / self.fraud

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            **asdict(self),
            "recall": self.recall,
            "precision": self.caught / self.alerts if self.alerts else None,
            "alerts_per_1000": 1000 * self.alerts / self.attempts,
        }


def sweep_thresholds(
    labels: NDArray[np.int64], scores: NDArray[np.float64]
) -> list[OperatingPoint]:
    if len(labels) != len(scores) or not np.isfinite(scores).all() or not labels.sum():
        raise ValueError("threshold sweep requires finite scores and positive labels")
    order = np.argsort(-scores, kind="stable")
    sorted_scores = scores[order]
    caught = np.cumsum(labels[order])
    ends = np.flatnonzero(np.r_[sorted_scores[1:] != sorted_scores[:-1], True])
    return [
        OperatingPoint(
            float(sorted_scores[end]), int(end) + 1, int(caught[end]), len(labels), int(caught[-1])
        )
        for end in ends
    ]


def best_under_capacity(points: list[OperatingPoint], alerts_per_1000: int) -> OperatingPoint:
    first = points[0]
    eligible = [
        point for point in points if point.alerts * 1000 <= alerts_per_1000 * point.attempts
    ]
    if not eligible:
        threshold = float(np.nextafter(first.threshold, np.inf))
        if threshold > 1:
            raise ValueError("top score ties exceed the alert budget at threshold 1")
        return OperatingPoint(threshold, 0, 0, first.attempts, first.fraud)
    return max(eligible, key=lambda point: (point.caught, -point.alerts))
