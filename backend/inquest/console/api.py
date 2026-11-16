from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import Connection, text
from sqlalchemy.engine import RowMapping

from inquest.auth.api import Actor, Identity
from inquest.console.simulator import ReplayCommand, ReplayStatus, Simulator
from inquest.investigation.api import guarded
from inquest.scoring.features import distance_km
from inquest.scoring.model import Contribution
from inquest.synthetic.models import City

CaseStatus = Literal["queued", "investigating", "review", "resolved", "escalated"]
Channel = Literal["card", "upi"]
Sort = Literal["time", "risk", "amount", "status", "merchant", "channel"]
SORT_COLUMNS = {
    "time": "t.occurred_at",
    "risk": "s.score",
    "amount": "t.amount_minor",
    "status": "c.status",
    "merchant": "m.alias",
    "channel": "t.channel",
}
TRANSACTION = """
    t.source_sequence, t.customer_id, t.merchant_id, m.alias AS merchant, t.device_id,
    t.occurred_at, t.amount_minor, t.currency, t.channel, t.flow, t.declined,
    g.name AS city, t.location_source
"""
TRANSACTION_JOINS = """
    JOIN fixture.merchants m ON (m.dataset_id, m.id) = (t.dataset_id, t.merchant_id)
    LEFT JOIN fixture.cities g ON (g.dataset_id, g.id) = (t.dataset_id, t.city_id)
"""
CASE_COLUMNS = """
    c.id AS case_id, c.dataset_id, c.replay_id, c.status, c.version, s.score, s.threshold,
    c.model_version, s.feature_version, s.contributions,
    i.id AS investigation_id, d.disposition, customer.alias AS customer
"""
CASE_FROM = f"""
    FROM operations.cases c
    JOIN operations.transaction_scores s
        USING (replay_id, dataset_id, source_sequence, model_version)
    JOIN fixture.transactions t
        ON (t.dataset_id, t.source_sequence) = (c.dataset_id, c.source_sequence)
    JOIN fixture.customers customer
        ON (customer.dataset_id, customer.id) = (t.dataset_id, t.customer_id)
    {TRANSACTION_JOINS}
    LEFT JOIN LATERAL (
        SELECT id FROM operations.investigations i
        WHERE (i.workspace_id, i.case_id) = (c.workspace_id, c.id)
        ORDER BY i.created_at DESC, i.id DESC LIMIT 1
    ) i ON true
    LEFT JOIN operations.decisions d
        ON (d.workspace_id, d.investigation_id) = (c.workspace_id, i.id)
"""


class Transaction(BaseModel):
    source_sequence: int
    customer_id: str
    merchant_id: str
    merchant: str
    device_id: str
    occurred_at: datetime
    amount_minor: int
    currency: str
    channel: Channel
    flow: Literal["purchase", "push", "collect"]
    declined: bool
    city: str | None
    location_source: Literal["physical", "remote"]


class CaseItem(Transaction):
    case_id: UUID
    dataset_id: str
    replay_id: UUID
    customer: str
    status: CaseStatus
    version: int
    score: float
    investigation_id: UUID | None
    disposition: Literal["block", "release", "escalate"] | None


class RecordedDecision(BaseModel):
    id: UUID
    analyst_id: UUID
    operation: Literal["approve", "override", "escalate"]
    disposition: Literal["block", "release", "escalate"]
    created_at: datetime
    note: str | None


class CaseDetail(CaseItem):
    threshold: float
    model_version: str
    feature_version: str
    contributions: list[Contribution]
    decision: RecordedDecision | None


class CasePage(BaseModel):
    items: list[CaseItem]
    counts: dict[CaseStatus, int]
    next_cursor: UUID | None


class Customer(BaseModel):
    id: str
    alias: str


class Travel(BaseModel):
    previous_sequence: int
    previous_city: str
    distance_km: float
    elapsed_seconds: float


class CustomerAttempt(Transaction):
    flagged: bool
    travel: Travel | None


class HistoryPage(BaseModel):
    customer: Customer
    items: list[CustomerAttempt]
    next_cursor: int | None


def point(row: RowMapping) -> City:
    return City(id=row["city_id"], name=row["city"], latitude=row["lat"], longitude=row["lon"])


def history(
    db: Connection,
    identity: Identity,
    simulator: Simulator,
    customer_id: str,
    before: int | None,
    through: int | None,
    limit: int,
) -> HistoryPage:
    params = {
        "dataset": simulator.fixture.dataset_id,
        "id": customer_id,
        "before": before,
        "through": through,
        "workspace": identity[0],
        "limit": limit + 1,
    }
    customer = (
        db.execute(
            text(
                "SELECT id, alias FROM fixture.customers WHERE dataset_id = :dataset AND id = :id"
            ),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Synthetic customer unavailable")
    rows = (
        db.execute(
            text(f"""
            SELECT {TRANSACTION}, t.city_id, g.latitude AS lat, g.longitude AS lon,
                EXISTS (
                    SELECT 1 FROM operations.cases c
                    WHERE c.workspace_id = :workspace
                        AND (c.dataset_id, c.source_sequence) = (t.dataset_id, t.source_sequence)
                ) AS flagged
            FROM fixture.transactions t {TRANSACTION_JOINS}
            WHERE t.dataset_id = :dataset AND t.customer_id = :id
                AND t.source_sequence <= least(:before, :through, 9223372036854775807)
            ORDER BY t.source_sequence DESC LIMIT :limit
        """),
            params,
        )
        .mappings()
        .all()
    )
    items = []
    for index, row in enumerate(rows[:limit]):
        prev = rows[index + 1] if index + 1 < len(rows) else None
        travel = None
        if prev and prev["city_id"] and row["city_id"]:
            travel = Travel(
                previous_sequence=prev["source_sequence"],
                previous_city=prev["city"],
                distance_km=round(distance_km(point(prev), point(row)), 1),
                elapsed_seconds=(row["occurred_at"] - prev["occurred_at"]).total_seconds(),
            )
        items.append(CustomerAttempt.model_validate(dict(row) | {"travel": travel}))
    return HistoryPage(
        customer=Customer.model_validate(customer),
        items=items,
        next_cursor=rows[limit]["source_sequence"] if len(rows) > limit else None,
    )


def console_router(simulator: Simulator, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/cases", tags=["cases"])
    def cases(
        response: Response,
        identity: Annotated[Identity, Depends(actor)],
        q: Annotated[str, Query(max_length=100)] = "",
        status: CaseStatus | None = None,
        channel: Channel | None = None,
        min_score: Annotated[float | None, Query(ge=0, le=1)] = None,
        sort: Sort = "time",
        direction: Literal["asc", "desc"] = "desc",
        after: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> CasePage:
        response.headers["Cache-Control"] = "no-store"
        order = SORT_COLUMNS[sort]
        operator = "<" if direction == "desc" else ">"
        workspace, analyst_id = identity
        params = {
            "workspace": workspace,
            "status": status,
            "channel": channel,
            "min_score": min_score,
            "q": q.strip(),
            "limit": limit + 1,
            "after": after,
        }
        with simulator.tenants.transaction(workspace_id=workspace, analyst_id=analyst_id) as db:
            rows = (
                db.execute(
                    text(f"""
                    WITH cursor AS (
                        SELECT {order} AS position, c.id {CASE_FROM}
                        WHERE c.workspace_id = :workspace AND c.id = :after
                    )
                    SELECT {CASE_COLUMNS}, {TRANSACTION} {CASE_FROM}
                    WHERE c.workspace_id = :workspace
                        AND c.status = coalesce(:status, c.status)
                        AND t.channel = coalesce(:channel, t.channel)
                        AND s.score >= coalesce(:min_score, 0)
                        AND (
                            strpos(lower(c.id::text), lower(:q)) > 0 OR
                            strpos(lower(m.alias), lower(:q)) > 0 OR
                            strpos(lower(customer.alias), lower(:q)) > 0 OR
                            strpos(lower(t.customer_id), lower(:q)) > 0 OR
                            strpos(lower('TX-' || t.source_sequence::text), lower(:q)) > 0
                        )
                        AND (CAST(:after AS uuid) IS NULL OR
                             ({order}, c.id) {operator} (SELECT position, id FROM cursor))
                    ORDER BY {order} {direction}, c.id {direction} LIMIT :limit
                """),
                    params,
                )
                .mappings()
                .all()
            )
            counts = db.execute(
                text("""
                    SELECT status, count(*) FROM operations.cases
                    WHERE workspace_id = :workspace GROUP BY status
                """),
                params,
            ).all()
        return CasePage(
            items=[CaseItem.model_validate(row) for row in rows[:limit]],
            counts={status: count for status, count in counts},
            next_cursor=rows[limit - 1]["case_id"] if len(rows) > limit else None,
        )

    @router.get("/cases/{case_id}", tags=["cases"])
    def case(
        case_id: UUID, response: Response, identity: Annotated[Identity, Depends(actor)]
    ) -> CaseDetail:
        response.headers["Cache-Control"] = "no-store"
        workspace, analyst_id = identity
        with simulator.tenants.transaction(workspace_id=workspace, analyst_id=analyst_id) as db:
            row = (
                db.execute(
                    text(f"""
                    SELECT {CASE_COLUMNS}, {TRANSACTION} {CASE_FROM}
                    WHERE c.workspace_id = :workspace AND c.id = :case
                """),
                    {"workspace": workspace, "case": case_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Case unavailable")
            decision = (
                db.execute(
                    text("""
                    SELECT d.id, d.analyst_id, d.operation, d.disposition, d.created_at,
                        n.body AS note
                    FROM operations.decisions d LEFT JOIN operations.notes n
                        ON (n.workspace_id, n.decision_id) = (d.workspace_id, d.id)
                    WHERE d.workspace_id = :workspace AND d.investigation_id = :run
                """),
                    {"workspace": workspace, "run": row["investigation_id"]},
                )
                .mappings()
                .one_or_none()
            )
        return CaseDetail.model_validate(dict(row) | {"decision": decision})

    @router.get("/customers", tags=["explorer"])
    def customers(
        identity: Annotated[Identity, Depends(actor)],
        q: Annotated[str, Query(max_length=100)] = "",
    ) -> list[Customer]:
        workspace, analyst_id = identity
        with simulator.tenants.transaction(workspace_id=workspace, analyst_id=analyst_id) as db:
            rows = (
                db.execute(
                    text("""
                    SELECT id, alias FROM fixture.customers
                    WHERE dataset_id = :dataset AND (
                        strpos(lower(id), lower(:q)) > 0 OR strpos(lower(alias), lower(:q)) > 0
                    )
                    ORDER BY CASE WHEN id = :q THEN 0 ELSE 1 END, alias, id LIMIT 30
                """),
                    {"dataset": simulator.fixture.dataset_id, "q": q.strip()},
                )
                .mappings()
                .all()
            )
        return [Customer.model_validate(row) for row in rows]

    @router.get("/customers/{customer_id}/transactions", tags=["explorer"])
    def transactions(
        customer_id: str,
        response: Response,
        identity: Annotated[Identity, Depends(actor)],
        before: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
        through: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ) -> HistoryPage:
        response.headers["Cache-Control"] = "no-store"
        with simulator.tenants.transaction(workspace_id=identity[0], analyst_id=identity[1]) as db:
            return history(db, identity, simulator, customer_id, before, through, limit)

    @router.get("/simulator", tags=["simulator"])
    def simulator_status(
        response: Response, identity: Annotated[Identity, Depends(actor)]
    ) -> ReplayStatus:
        response.headers["Cache-Control"] = "no-store"
        return simulator.status(identity)

    @router.post("/simulator/commands", tags=["simulator"])
    def simulator_command(
        action: ReplayCommand, identity: Annotated[Identity, Depends(actor)]
    ) -> ReplayStatus:
        return guarded(lambda: simulator.command(identity, action))

    return router
