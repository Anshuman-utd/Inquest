from collections.abc import Mapping
from typing import Annotated
from uuid import uuid5

from pydantic import Field, TypeAdapter
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from inquest.db.tenant import TenantDatabase
from inquest.investigation.contracts import (
    MAX_OBSERVATION_BYTES,
    DatabaseEvidence,
    DatabaseObservation,
    DatabaseRequest,
    EntityRequest,
    Evidence,
    HistoryRequest,
    ToolScope,
    TransactionObservation,
    UnavailableEvidence,
)
from inquest.investigation.policy import PolicyEvidence, PolicyIndex, PolicySearchRequest
from inquest.investigation.repository import Observations, focal_transaction, resolve_case

ToolRequest = Annotated[
    EntityRequest | HistoryRequest | PolicySearchRequest, Field(discriminator="tool")
]
TOOL_REQUESTS: TypeAdapter[ToolRequest] = TypeAdapter(ToolRequest)
ToolEvidence = DatabaseEvidence | PolicyEvidence | UnavailableEvidence


class InvestigationTools:
    def __init__(
        self, tenants: TenantDatabase, tool_engine: Engine, policy_index: PolicyIndex
    ) -> None:
        self._tenants = tenants
        self._tool_engine = tool_engine
        self._policy_index = policy_index

    def execute(
        self, scope: ToolScope, call_sequence: int, arguments: Mapping[str, object]
    ) -> ToolEvidence:
        request = TOOL_REQUESTS.validate_python(arguments)
        if type(call_sequence) is not int or not 1 <= call_sequence <= 2**31 - 1:
            raise ValueError("call sequence must be a positive database integer")

        with self._tenants.transaction(
            workspace_id=scope.workspace_id, analyst_id=scope.analyst_id
        ) as connection:
            position = resolve_case(connection, scope.workspace_id, scope.investigation_id)

        identity = Evidence(
            evidence_id=uuid5(scope.investigation_id, f"tool-call:{call_sequence}"),
            investigation_id=scope.investigation_id,
            call_sequence=call_sequence,
            cutoff=position,
        )
        if isinstance(request, PolicySearchRequest):
            result: DatabaseEvidence | PolicyEvidence = PolicyEvidence(
                **identity.model_dump(), observation=self._policy_index.search(request)
            )
        else:
            try:
                with self._tool_engine.begin() as connection:
                    connection.execute(
                        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    )
                    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                    connection.execute(text("SET LOCAL statement_timeout = '3s'"))
                    focal = focal_transaction(connection, position)
                    observation = self._observe(request, Observations(connection, position, focal))
                result = DatabaseEvidence(**identity.model_dump(), observation=observation)
            except SQLAlchemyError:
                return UnavailableEvidence(
                    **identity.model_dump(), tool=request.tool, reason="data_unavailable"
                )
        if len(result.model_dump_json().encode()) > MAX_OBSERVATION_BYTES:
            return UnavailableEvidence(
                **identity.model_dump(), tool=request.tool, reason="observation_too_large"
            )
        return result

    @staticmethod
    def _observe(request: DatabaseRequest, data: Observations) -> DatabaseObservation:
        if isinstance(request, HistoryRequest):
            return data.customer_history(request.window_days)

        match request.tool:
            case "get_transaction":
                return TransactionObservation(transaction=data.focal)
            case "get_customer_profile":
                return data.customer_profile()
            case "velocity_check":
                return data.velocity()
            case "geo_mismatch_check":
                return data.geography()
            case "device_check":
                return data.device()
            case "merchant_risk_lookup":
                return data.merchant()
