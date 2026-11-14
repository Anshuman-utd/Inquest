from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from inquest.investigation.contracts import Contract
from inquest.investigation.tools import ToolEvidence

Scalar = str | int | float | bool
Action = Literal["block", "release", "escalate"]
Verdict = Literal["fraud", "legit", "needs_human_review"]


class Fact(Contract):
    evidence_id: UUID
    field: str = Field(min_length=1, max_length=100)
    value: Scalar


class Draft(Contract):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    recommended_action: Action
    evidence: Annotated[tuple[Fact, ...], Field(max_length=8)]

    @model_validator(mode="after")
    def compatible(self) -> Self:
        actions = {"fraud": "block", "legit": "release", "needs_human_review": "escalate"}
        if actions[self.verdict] != self.recommended_action:
            raise ValueError("verdict and recommendation disagree")
        return self


class Report(Draft):
    status: Literal["verified", "inconclusive"]
    reason: Literal["insufficient_evidence", "provider_unavailable", "invalid_report"] | None = None


def verify(draft: Draft, results: list[ToolEvidence]) -> Report:
    successful = {item.evidence_id: item for item in results if item.status == "ok"}
    distinct = set()
    supporting_tools = set()
    for fact in draft.evidence:
        key = (fact.evidence_id, fact.field)
        if key in distinct:
            raise ValueError("repeated fact")
        distinct.add(key)
        result = successful.get(fact.evidence_id)
        if result is None:
            raise ValueError("unknown or unavailable evidence")
        value: object = result.observation.model_dump(mode="json")
        for part in fact.field.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
                value = value[int(part)]
            else:
                raise ValueError("unknown evidence field")
        if type(value) is not type(fact.value) or value != fact.value:
            raise ValueError("evidence value mismatch")
        tool = result.observation.tool
        if draft.recommended_action == "block" and (
            (tool == "velocity_check" and fact.field == "last_5m.attempts" and int(fact.value) >= 3)
            or (
                tool == "device_check"
                and fact.field == "distinct_customers_1h"
                and int(fact.value) >= 2
            )
            or (
                tool == "merchant_risk_lookup"
                and fact.field == "distinct_customers_5m"
                and int(fact.value) >= 3
            )
            or (
                tool == "geo_mismatch_check"
                and fact.field == "implied_speed_kmh"
                and float(fact.value) >= 900
            )
        ):
            supporting_tools.add(tool)
        if draft.recommended_action == "release" and (
            (
                tool == "device_check"
                and fact.field == "customer_attempts_on_device_30d"
                and int(fact.value) >= 3
            )
            or (
                tool == "merchant_risk_lookup"
                and fact.field == "customer_attempts_at_merchant_30d"
                and int(fact.value) >= 3
            )
        ):
            supporting_tools.add(tool)
    if draft.recommended_action != "escalate" and len(supporting_tools) < 2:
        raise ValueError("recommendation requires corroboration from two tool types")
    return Report(**draft.model_dump(), status="verified")
