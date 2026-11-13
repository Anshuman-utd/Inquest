from pathlib import Path

import numpy as np
import pytest

from inquest.scoring.features import FEATURE_NAMES
from inquest.scoring.model import Scorer, calibrated_probability

ARTIFACT = Path("models/scorer")


def test_native_shap_values_reconstruct_margin_and_serve_top_five() -> None:
    scorer = Scorer(ARTIFACT)
    features = (0.0, 1.0, *(float("nan") for _ in FEATURE_NAMES[2:]))
    score = scorer.predict(features)
    row = np.asarray([features])
    shap = scorer.booster.predict(row, pred_contrib=True, num_threads=1)[0]
    margin = scorer.booster.predict(row, raw_score=True, num_threads=1)[0]
    assert score.raw_margin == pytest.approx(margin)
    assert score.base_margin == pytest.approx(shap[-1])
    assert float(shap.sum()) == pytest.approx(margin)
    manifest = scorer.manifest
    assert score.fraud_probability == pytest.approx(
        calibrated_probability(
            float(margin), manifest.calibration_slope, manifest.calibration_intercept
        )
    )
    ordered = sorted(range(len(features)), key=lambda index: -abs(shap[index]))[:5]
    assert [item.feature for item in score.top_contributions] == [FEATURE_NAMES[i] for i in ordered]
    assert [item.raw_margin_delta for item in score.top_contributions] == pytest.approx(
        shap[ordered]
    )
    assert score.model_dump_json()


def test_model_loader_rejects_modified_artifact(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_bytes((ARTIFACT / "manifest.json").read_bytes())
    (tmp_path / "lightgbm.txt").write_text("tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        Scorer(tmp_path)
