from typing import Any

from inquest.evaluation.evidence_plan import compact_evidence, next_evidence
from inquest.investigation.graph import State


def test_focused_plan_uses_same_entity_tools_without_policy() -> None:
    observations: list[dict[str, Any]] = [
        {"observation": {"tool": "get_transaction", "transaction": {"channel": "upi"}}},
        {"observation": {"tool": "velocity_check"}},
        {"observation": {"tool": "device_check"}},
        {"observation": {"tool": "merchant_risk_lookup", "distinct_customers_5m": 4}},
        {"observation": {"tool": "geo_mismatch_check"}},
    ]
    state: State = {"observations": observations}
    request = next_evidence(state, policy=True)["request"]
    assert request == {
        "tool": "search_policy_docs",
        "query": "mule cash out recipient concentration several customers UPI",
    }
    assert next_evidence(state, policy=False)["request"] is None


def test_compact_evidence_preserves_exact_fields_for_verification() -> None:
    state: State = {
        "observations": [
            {
                "evidence_id": "a",
                "observation": {
                    "tool": "device_check",
                    "customer_attempts_on_device_30d": 3,
                    "distinct_customers_1h": 2,
                    "device_attempts_30d": 15,
                },
            }
        ]
    }
    compact = compact_evidence(state)
    assert compact["observations"] == [
        {
            "evidence_id": "a",
            "observation": {
                "tool": "device_check",
                "customer_attempts_on_device_30d": 3,
                "distinct_customers_1h": 2,
            },
        }
    ]
    assert state["observations"][0]["observation"]["device_attempts_30d"] == 15
