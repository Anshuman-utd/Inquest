from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from inquest.investigation.contracts import Contract
from inquest.investigation.reports import Action, Report
from inquest.investigation.tools import ToolEvidence, ToolRequest

Mode = Literal["live", "replay"]


class ModePayload(Contract):
    mode: Mode


class SummaryPayload(Contract):
    summary: str


class TriagePayload(SummaryPayload, ModePayload):
    pass


class ToolStartedPayload(Contract):
    call_sequence: int
    input: ToolRequest


class ToolObservedPayload(SummaryPayload):
    result: ToolEvidence


class RecordingPayload(SummaryPayload):
    reason: str | None


class ReportPayload(Contract):
    report: Report


class DecisionPayload(Contract):
    decision_id: UUID
    disposition: Action


class Queued(Contract):
    kind: Literal["queued"]
    payload: ModePayload


class Triage(Contract):
    kind: Literal["triage"]
    payload: TriagePayload


class ToolStarted(Contract):
    kind: Literal["tool_started"]
    payload: ToolStartedPayload


class ToolObserved(Contract):
    kind: Literal["tool_observed"]
    payload: ToolObservedPayload


class Recording(Contract):
    kind: Literal["recording_used", "recording_unavailable"]
    payload: RecordingPayload


class ReportReady(Contract):
    kind: Literal["report_ready"]
    payload: ReportPayload


class Decision(Contract):
    kind: Literal["decision_recorded", "completed"]
    payload: DecisionPayload


class Failed(Contract):
    kind: Literal["failed"]
    payload: SummaryPayload


InvestigationEvent = Annotated[
    Queued | Triage | ToolStarted | ToolObserved | Recording | ReportReady | Decision | Failed,
    Field(discriminator="kind"),
]
EVENTS: TypeAdapter[InvestigationEvent] = TypeAdapter(InvestigationEvent)
