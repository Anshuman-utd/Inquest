import argparse
import json
from collections import Counter, defaultdict
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from random import Random
from typing import Literal

from pydantic import BaseModel

from inquest.scoring.features import chronological_features
from inquest.scoring.model import Scorer, calibrated_probability
from inquest.synthetic.generator import GENERATOR_VERSION, generate
from inquest.synthetic.models import GeneratorConfig, Truth
from inquest.synthetic.seed import load_fixture

CohortName = Literal["pilot", "held_out", "confirmation"]
SEEDS: dict[CohortName, int] = {"pilot": 2104, "held_out": 2105, "confirmation": 2106}


class Sample(BaseModel):
    sequence: int
    stratum: str
    population: int
    sampled: int
    score: float

    @property
    def weight(self) -> float:
        return self.population / self.sampled


class CohortManifest(BaseModel):
    name: CohortName
    config: GeneratorConfig
    dataset_id: str
    model_version: str
    model_sha256: str
    threshold: float
    sampling_seed: int
    sample_sha256: str
    attempts: int
    fraud: int
    alerted: int
    alerted_fraud: int
    fraud_by_scenario: dict[str, int]
    alerted_fraud_by_scenario: dict[str, int]
    samples: list[Sample]


def stratum(label: Truth) -> str:
    if label.is_fraud:
        return f"fraud/{label.scenario}"
    return "legit/scenario" if label.scenario else "legit/routine"


def build_cohort(name: CohortName, scorer: Scorer, database_url: str) -> CohortManifest:
    base = GeneratorConfig.model_validate_json(Path("fixtures/india.json").read_text())
    config = base.model_copy(
        update={
            "seed": SEEDS[name],
            "start": base.start.replace(month=6 if name == "pilot" else 11, day=1),
            "days": 150,
            "customer_count": 650,
            "merchant_count": 160,
        }
    )
    if name == "confirmation":
        config = config.model_copy(
            update={
                "attempts_per_customer_week": config.attempts_per_customer_week * 1.2,
                "amounts": tuple(
                    item.model_copy(update={"median_minor": round(item.median_minor * 1.15)})
                    for item in config.amounts
                ),
            }
        )
    world = generate(config)
    cutoff = config.start + timedelta(days=30)
    warmup = {
        label.episode_id
        for payment, label in zip(world.transactions, world.truth, strict=True)
        if payment.occurred_at < cutoff and label.episode_id is not None
    }
    eligible = {
        label.source_sequence: label
        for payment, label in zip(world.transactions, world.truth, strict=True)
        if payment.occurred_at >= cutoff and label.episode_id not in warmup
    }
    fraud_counts: Counter[str] = Counter()
    alerted_fraud: Counter[str] = Counter()
    groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
    model = scorer.manifest
    # Batch inference keeps cohort construction fast. Serving contributions are fetched only
    # for sampled alerts, using the same point-in-time feature extractor.
    features = list(chronological_features(world, eligible.keys()))
    margins = scorer.booster.predict(features, raw_score=True, num_threads=1)
    for label, margin in zip(eligible.values(), margins, strict=True):
        score = calibrated_probability(
            float(margin), model.calibration_slope, model.calibration_intercept
        )
        if label.is_fraud and label.scenario:
            fraud_counts[label.scenario] += 1
        if score >= model.threshold:
            groups[stratum(label)].append((label.source_sequence, score))
            if label.is_fraud and label.scenario:
                alerted_fraud[label.scenario] += 1
    sampling_seed = 715
    rng = Random(sampling_seed)
    samples: list[Sample] = []
    for group, members in sorted(groups.items()):
        if name == "pilot" and group not in {
            "fraud/card_testing",
            "fraud/mule_cash_out",
            "legit/routine",
            "legit/scenario",
        }:
            continue
        count = min(len(members), 1 if name == "pilot" or group.startswith("fraud/") else 4)
        samples.extend(
            Sample(
                sequence=sequence,
                stratum=group,
                population=len(members),
                sampled=count,
                score=score,
            )
            for sequence, score in rng.sample(members, count)
        )
    samples.sort(key=lambda item: item.sequence)
    digest = sha256(json.dumps([s.model_dump() for s in samples], sort_keys=True).encode())
    expected_id = f"v{GENERATOR_VERSION}-{sha256(world.model_dump_json().encode()).hexdigest()}"
    assert load_fixture(world, database_url) == expected_id
    return CohortManifest(
        name=name,
        config=config,
        dataset_id=expected_id,
        model_version=model.model_version,
        model_sha256=model.model_sha256,
        threshold=model.threshold,
        sampling_seed=sampling_seed,
        sample_sha256=digest.hexdigest(),
        attempts=len(eligible),
        fraud=sum(fraud_counts.values()),
        alerted=sum(map(len, groups.values())),
        alerted_fraud=sum(alerted_fraud.values()),
        fraud_by_scenario=dict(fraud_counts),
        alerted_fraud_by_scenario=dict(alerted_fraud),
        samples=samples,
    )


def main() -> None:
    from inquest.settings import Settings

    parser = argparse.ArgumentParser(description="Freeze a stratified alert sample")
    parser.add_argument("name", choices=list(SEEDS))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    settings = Settings()
    manifest = build_cohort(
        args.name, Scorer(settings.scorer_directory), settings.migration_database_url
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(manifest.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
