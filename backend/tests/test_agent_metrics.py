from pathlib import Path

from inquest.evaluation.agent_cohort import CohortManifest, Sample
from inquest.evaluation.agent_metrics import aggregate
from inquest.synthetic.models import GeneratorConfig


def test_weighted_metrics_preserve_below_threshold_misses_and_abstentions() -> None:
    config = GeneratorConfig.model_validate_json(Path("fixtures/india.json").read_text())
    manifest = CohortManifest(
        name="held_out",
        config=config,
        dataset_id="d",
        model_version="v",
        model_sha256="m",
        threshold=0.01,
        sampling_seed=1,
        sample_sha256="s",
        attempts=100,
        fraud=5,
        alerted=10,
        alerted_fraud=4,
        fraud_by_scenario={"card_testing": 5},
        alerted_fraud_by_scenario={"card_testing": 4},
        samples=[
            Sample(sequence=1, stratum="fraud/card_testing", population=4, sampled=1, score=0.1),
            Sample(sequence=2, stratum="legit/routine", population=6, sampled=1, score=0.05),
        ],
    )
    common = {"tool_calls": 1, "requests": 1, "retries": 0, "cache_hits": 0}
    rows = [
        common
        | {
            "sequence": 1,
            "stratum": "fraud/card_testing",
            "is_fraud": True,
            "action": "escalate",
            "weight": 4,
            "grounded": False,
            "failure": "provider_unavailable",
        },
        common
        | {
            "sequence": 2,
            "stratum": "legit/routine",
            "is_fraud": False,
            "action": "release",
            "weight": 6,
            "grounded": True,
        },
    ]
    result = aggregate(manifest, rows)
    assert result["alert_fraud_retained"] == 1
    assert result["end_to_end_fraud_retained"] == 0.8
    assert result["alert_triage_accuracy"] == 1
    assert result["end_to_end_triage_accuracy"] == 0.99
    assert result["resolution_coverage"] == 0.6
    assert result["resolved_accuracy"] == 1
    assert result["weighted_fraud_failure"] == 4
    assert result["sample_true_releases"] == 1
