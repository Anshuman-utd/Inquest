import numpy as np

from inquest.evaluation.train import assign_split, capacity_point, operating_point


def test_chronological_split_boundaries() -> None:
    assert [assign_split(day, 180) for day in (0, 29, 30, 107, 108, 119, 120, 149, 150, 179)] == [
        "warmup",
        "warmup",
        "train",
        "train",
        "calibration",
        "calibration",
        "validation",
        "validation",
        "test",
        "test",
    ]


def test_threshold_uses_highest_feasible_score_and_counts_ties() -> None:
    labels = np.zeros(1_000, dtype=np.int64)
    labels[:10] = 1
    scores = np.linspace(1, 0, len(labels))
    assert operating_point(labels, scores) == scores[8]
    scores[8:32] = scores[8]
    assert operating_point(labels, scores) is None
    assert capacity_point(scores) == scores[7]
