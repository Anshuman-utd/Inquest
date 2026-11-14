import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import fmean, median
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text

from inquest.evaluation.agent_cohort import CohortManifest
from inquest.settings import Settings

# Equivalent public Groq list pricing for GPT-OSS 20B, in USD per million tokens.
INPUT_PRICE = 0.075
OUTPUT_PRICE = 0.30


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def aggregate(manifest: CohortManifest, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if {row["sequence"] for row in rows} != {sample.sequence for sample in manifest.samples}:
        raise ValueError("incomplete cohort")
    counts: Counter[tuple[str, str]] = Counter()
    groups: dict[str, Counter[str]] = {}
    failure_codes: Counter[str] = Counter()
    for row in rows:
        label = "fraud" if row["is_fraud"] else "legit"
        action = row["action"]
        counts[label, action] += row["weight"]
        group = groups.setdefault(row["stratum"], Counter())
        group[action] += 1
        if row.get("failure"):
            group["failures"] += 1
            failure_codes[row.get("fallback_reason") or row["failure"]] += 1
            counts[label, "failure"] += row["weight"]
        if row.get("grounded") is False and not row.get("failure"):
            group["unsupported"] += 1
    fraud = sum(row["weight"] for row in rows if row["is_fraud"])
    legit = sum(row["weight"] for row in rows if not row["is_fraud"])
    retained = fraud - counts["fraud", "release"]
    cleared = counts["legit", "release"]
    resolved = sum(
        counts[label, action] for label in ("legit", "fraud") for action in ("block", "release")
    )
    correct = cleared + counts["fraud", "block"]
    classes_covered = {row["stratum"] for row in rows}
    complete = (
        all(f"fraud/{name}" in classes_covered for name in manifest.alerted_fraud_by_scenario)
        and abs(legit + fraud - manifest.alerted) < 1e-8
    )
    latencies = sorted(row["latency_seconds"] for row in rows if "latency_seconds" in row)
    p95 = latencies[(95 * len(latencies) + 99) // 100 - 1] if latencies else None
    input_tokens = sum(row.get("input_tokens", 0) for row in rows)
    output_tokens = sum(row.get("output_tokens", 0) for row in rows)
    grounded_values = [row["grounded"] for row in rows if row["grounded"] is not None]
    return {
        "sample_size": len(rows),
        "sample_fraud": sum(row["is_fraud"] for row in rows),
        "sample_actions": dict(Counter(row["action"] for row in rows)),
        "sample_false_releases": sum(
            row["is_fraud"] and row["action"] == "release" for row in rows
        ),
        "sample_true_releases": sum(
            not row["is_fraud"] and row["action"] == "release" for row in rows
        ),
        "sample_fraud_blocked": sum(row["is_fraud"] and row["action"] == "block" for row in rows),
        "sample_legit_blocked": sum(
            not row["is_fraud"] and row["action"] == "block" for row in rows
        ),
        "covers_all_alert_strata": complete,
        "weighted_fraud": fraud,
        "weighted_legit": legit,
        "weighted_legit_released": cleared,
        "weighted_legit_blocked": counts["legit", "block"],
        "weighted_legit_escalated": counts["legit", "escalate"],
        "weighted_fraud_escalated": counts["fraud", "escalate"],
        "weighted_fraud_failure": counts["fraud", "failure"],
        "weighted_legit_failure": counts["legit", "failure"],
        "legit_alerts_cleared": ratio(cleared, legit),
        "alert_fraud_retained": ratio(retained, fraud),
        "end_to_end_fraud_retained": ratio(retained, manifest.fraud) if complete else None,
        "alert_triage_accuracy": ratio(retained + cleared, fraud + legit),
        "end_to_end_triage_accuracy": (
            ratio(
                retained + cleared + manifest.attempts - manifest.fraud - legit, manifest.attempts
            )
            if complete
            else None
        ),
        "resolved_accuracy": ratio(correct, resolved),
        "resolution_coverage": ratio(resolved, fraud + legit),
        "correct_resolved_share": ratio(correct, fraud + legit),
        "grounded_sample": sum(grounded_values),
        "grounding_denominator": len(grounded_values),
        "scenarios": {key: dict(value) for key, value in sorted(groups.items())},
        "failure_codes": dict(failure_codes),
        "tool_calls": sum(row["tool_calls"] for row in rows),
        "mean_tool_calls": fmean(row["tool_calls"] for row in rows),
        "policy_calls": sum(row.get("policy_calls", 0) for row in rows),
        "provider_requests": sum(row["requests"] for row in rows),
        "provider_retries": sum(row["retries"] for row in rows),
        "cache_hits": sum(row["cache_hits"] for row in rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "accounted_tokens": sum(row.get("accounted_tokens", 0) for row in rows),
        "equivalent_list_cost_usd": (input_tokens * INPUT_PRICE + output_tokens * OUTPUT_PRICE)
        / 1e6,
        "actual_cost_usd": None,
        "p50_seconds": median(latencies) if latencies else None,
        "p95_seconds": p95,
    }


def publish(path: Path) -> None:
    data = json.loads(path.read_text())
    manifest = CohortManifest.model_validate(data["cohort"])
    metrics = {arm: aggregate(manifest, rows) for arm, rows in data["rows"].items()}
    engine = create_engine(Settings().evaluation_database_url)
    try:
        with engine.begin() as db:
            for arm, result in metrics.items():
                db.execute(
                    text("""
                    UPDATE evaluation.eval_runs SET metrics = CAST(:metrics AS jsonb)
                    WHERE id = :run
                """),
                    {"run": UUID(data["run_ids"][arm]), "metrics": json.dumps(result)},
                )
    finally:
        engine.dispose()
    output = path.with_name("metrics.json")
    summary = {
        "schema_version": 1,
        "run_ids": data["run_ids"],
        "cohort": data["cohort"],
        "arms": metrics,
    }
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aggregate and publish agent evaluation metrics")
    parser.add_argument("results", type=Path)
    publish(parser.parse_args().results)
