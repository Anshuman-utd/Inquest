from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter

from inquest.investigation.contracts import Contract
from inquest.investigation.reports import Action, Draft, Fact, Report, Scalar, Verdict, verify
from inquest.investigation.tools import ToolEvidence


class RecordedFact(Contract):
    tool: str
    field: str
    value: Scalar


class Recording(Contract):
    dataset_id: str
    source_sequence: int
    verdict: Verdict
    recommended_action: Action
    confidence: float
    facts: tuple[RecordedFact, ...]


class Recordings:
    def __init__(self, path: Path) -> None:
        items = TypeAdapter(list[Recording]).validate_json(path.read_text())
        self.items = {(item.dataset_id, item.source_sequence): item for item in items}
        if len(self.items) != len(items):
            raise ValueError("duplicate recorded investigation")

    def report(self, results: list[ToolEvidence]) -> Report | None:
        if not results:
            return None
        cutoff = results[0].cutoff
        item = self.items.get((cutoff.dataset_id, cutoff.source_sequence))
        if item is None:
            return None
        ids: dict[str, UUID] = {
            result.observation.tool: result.evidence_id
            for result in results
            if result.status == "ok"
        }
        if any(fact.tool not in ids for fact in item.facts):
            return None
        return verify(
            Draft(
                verdict=item.verdict,
                confidence=item.confidence,
                recommended_action=item.recommended_action,
                evidence=tuple(
                    Fact(evidence_id=ids[fact.tool], field=fact.field, value=fact.value)
                    for fact in item.facts
                ),
            ),
            results,
        )
