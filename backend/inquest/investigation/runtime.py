import json
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, text

from inquest.investigation.contracts import Contract, ToolScope
from inquest.investigation.provider import ProviderUnavailable
from inquest.investigation.reports import Action, Report
from inquest.investigation.repository import InvestigationUnavailable


class Conflict(Exception):
    """The current investigation state cannot accept the request."""


class RateLimited(Exception):
    """The request exceeded the configured per-IP rate."""


class DecisionRequest(Contract):
    operation: Literal["approve", "override", "escalate"]
    expected_case_version: Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]
    action: Action | None = None
    note: Annotated[str, Field(max_length=1000)] = ""

    @model_validator(mode="after")
    def check_override(self) -> "DecisionRequest":
        if (self.operation == "override") != (self.action is not None):
            raise ValueError("action is required only for an override")
        return self


def locked_run(connection: Connection, scope: ToolScope) -> Any:
    row = connection.execute(
        text("""
            SELECT id, case_id, status, mode, started_at, used_tokens, report
            FROM operations.investigations
            WHERE workspace_id = :workspace AND id = :id FOR UPDATE
        """),
        {"workspace": scope.workspace_id, "id": scope.investigation_id},
    ).one_or_none()
    if row is None:
        raise InvestigationUnavailable
    return row


def event(
    connection: Connection, scope: ToolScope, key: str, kind: str, payload: dict[str, Any]
) -> None:
    # Callers hold the investigation row lock, or own its uncommitted insert.
    connection.execute(
        text("""
            INSERT INTO operations.investigation_events
                (workspace_id, investigation_id, sequence, deduplication_key, kind, payload)
            SELECT :workspace, :id, coalesce(max(sequence), 0) + 1,
                :key, :kind, CAST(:payload AS jsonb)
            FROM operations.investigation_events WHERE workspace_id = :workspace
                AND investigation_id = :id
            ON CONFLICT (workspace_id, investigation_id, deduplication_key) DO NOTHING
        """),
        {
            "workspace": scope.workspace_id,
            "id": scope.investigation_id,
            "key": key,
            "kind": kind,
            "payload": json.dumps(payload),
        },
    )


def consume_ip(connection: Connection, ip_hash: str, limit: int) -> None:
    connection.execute(
        text("""
        DELETE FROM operations.ip_rate_limits WHERE window_started_at < now() - interval '1 day'
    """)
    )
    allowed = connection.execute(
        text("""
            INSERT INTO operations.ip_rate_limits (action, ip_hash, window_started_at, attempts)
            VALUES ('investigate', :ip, date_trunc('minute', now()), 1)
            ON CONFLICT (action, ip_hash, window_started_at) DO UPDATE SET
                attempts = operations.ip_rate_limits.attempts + 1
                WHERE operations.ip_rate_limits.attempts < :limit
            RETURNING attempts
        """),
        {"ip": ip_hash, "limit": limit},
    ).scalar_one_or_none()
    if allowed is None:
        raise RateLimited


def take_live_slot(connection: Connection, workspace: UUID, limit: int) -> bool:
    enabled = connection.execute(
        text("SELECT llm_enabled FROM operations.runtime_controls WHERE singleton")
    ).scalar_one()
    if not enabled:
        return False
    return (
        connection.execute(
            text("""
            INSERT INTO operations.workspace_usage (workspace_id, utc_day, live_starts)
            VALUES (:workspace, :day, 1)
            ON CONFLICT (workspace_id, utc_day) DO UPDATE SET
                live_starts = operations.workspace_usage.live_starts + 1
                WHERE operations.workspace_usage.live_starts < :limit
            RETURNING live_starts
        """),
            {"workspace": workspace, "day": datetime.now(UTC).date(), "limit": limit},
        ).scalar_one_or_none()
        is not None
    )


def reserve_tokens(
    connection: Connection,
    scope: ToolScope,
    amount: int,
    daily_limit: int,
    investigation_limit: int,
    *,
    day: date,
) -> None:
    run = locked_run(connection, scope)
    if run.used_tokens + amount > investigation_limit:
        raise ProviderUnavailable("investigation_budget_exhausted")
    enabled = connection.execute(
        text("SELECT llm_enabled FROM operations.runtime_controls WHERE singleton")
    ).scalar_one()
    if not enabled or amount > daily_limit:
        raise ProviderUnavailable("global_budget_disabled")
    reserved = connection.execute(
        text("""
            INSERT INTO operations.global_usage (utc_day, reserved_tokens) VALUES (:day, :amount)
            ON CONFLICT (utc_day) DO UPDATE SET
                reserved_tokens = operations.global_usage.reserved_tokens + excluded.reserved_tokens
                WHERE operations.global_usage.reserved_tokens + excluded.reserved_tokens <= :limit
            RETURNING reserved_tokens
        """),
        {"day": day, "amount": amount, "limit": daily_limit},
    ).scalar_one_or_none()
    if reserved is None:
        raise ProviderUnavailable("global_budget_exhausted")
    connection.execute(
        text(
            "UPDATE operations.investigations SET used_tokens = used_tokens + :amount "
            "WHERE id = :id"
        ),
        {"amount": amount, "id": scope.investigation_id},
    )


def disposition(request: DecisionRequest, report: Report) -> Action:
    if request.operation == "escalate":
        return "escalate"
    if request.operation == "override":
        assert request.action is not None
        return request.action
    return report.recommended_action
