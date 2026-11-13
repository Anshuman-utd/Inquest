from collections.abc import Mapping
from uuid import uuid5

from pydantic import TypeAdapter
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from inquest.db.tenant import TenantDatabase
from inquest.investigation.contracts import (
    MAX_OBSERVATION_BYTES,
    Cutoff,
    DatabaseEvidence,
    DatabaseObservation,
    DatabaseRequest,
    Evidence,
    HistoryRequest,
    ToolScope,
    TransactionObservation,
    UnavailableEvidence,
)
from inquest.investigation.repository import Observations, focal_transaction, resolve_case

DATABASE_REQUESTS: TypeAdapter[DatabaseRequest] = TypeAdapter(DatabaseRequest)


class InvestigationTools:
    def __init__(self, tenants: TenantDatabase, tool_engine: Engine) -> None:
        self._tenants = tenants
        self._tool_engine = tool_engine

    def execute(
        self, scope: ToolScope, call_sequence: int, arguments: Mapping[str, object]
    ) -> DatabaseEvidence | UnavailableEvidence:
        request = DATABASE_REQUESTS.validate_python(arguments)
        if type(call_sequence) is not int or not 1 <= call_sequence <= 2**31 - 1:
            raise ValueError("call sequence must be a positive database integer")

        with self._tenants.transaction(
            workspace_id=scope.workspace_id, analyst_id=scope.analyst_id
        ) as connection:
            position = resolve_case(connection, scope.workspace_id, scope.investigation_id)

        identity = None
        try:
            with self._tool_engine.begin() as connection:
                connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                connection.execute(text("SET LOCAL statement_timeout = '3s'"))
                focal = focal_transaction(connection, position)
                identity = Evidence(
                    evidence_id=uuid5(scope.investigation_id, f"tool-call:{call_sequence}"),
                    investigation_id=scope.investigation_id,
                    call_sequence=call_sequence,
                    cutoff=Cutoff(
                        occurred_at=focal.occurred_at, source_sequence=focal.source_sequence
                    ),
                )
                observation = self._observe(request, Observations(connection, position, focal))
        except SQLAlchemyError:
            if identity is None:
                raise
            return UnavailableEvidence(
                **identity.model_dump(), tool=request.tool, reason="data_unavailable"
            )
        result = DatabaseEvidence(**identity.model_dump(), observation=observation)
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
