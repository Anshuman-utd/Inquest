import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from inquest.auth.api import Actor, client_ip_hash
from inquest.db.tenant import WorkspaceAccessDenied
from inquest.investigation.contracts import ToolScope
from inquest.investigation.events import EVENTS
from inquest.investigation.reports import Report
from inquest.investigation.repository import InvestigationUnavailable
from inquest.investigation.runtime import Conflict, DecisionRequest, RateLimited
from inquest.investigation.service import Investigations

log = logging.getLogger(__name__)
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


class Started(BaseModel):
    investigation_id: UUID


class Recorded(BaseModel):
    decision_id: UUID


class Snapshot(BaseModel):
    status: str
    mode: str
    report: Report | None
    case_version: int


@asynccontextmanager
async def supervise(
    service: Investigations, replay_step: Callable[[], bool] | None = None
) -> AsyncIterator[None]:
    stopped = asyncio.Event()

    async def worker(step: Callable[[], bool]) -> None:
        while not stopped.is_set():
            try:
                ready = await run_in_threadpool(step)
                delay = 0.05 if ready else 2
            except Exception:
                log.exception("Background worker will retry")
                delay = 5
            try:
                await asyncio.wait_for(stopped.wait(), timeout=delay)
            except TimeoutError:
                pass

    tasks = [asyncio.create_task(worker(service.work_once))]
    if replay_step is not None:
        tasks.append(asyncio.create_task(worker(replay_step)))
    try:
        yield
    finally:
        stopped.set()
        await asyncio.gather(*tasks)


def guarded[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except (InvestigationUnavailable, WorkspaceAccessDenied) as exc:
        raise HTTPException(status_code=404, detail="Investigation or case unavailable") from exc
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail="Rate limit reached") from exc


def investigation_router(service: Investigations, ip_key: bytes, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["investigations"])

    def scope(identity: tuple[UUID, UUID], investigation_id: UUID) -> ToolScope:
        return ToolScope(
            workspace_id=identity[0], analyst_id=identity[1], investigation_id=investigation_id
        )

    @router.post("/cases/{case_id}/investigations", status_code=202)
    def start(
        case_id: UUID,
        request: Request,
        key: Key,
        identity: Annotated[tuple[UUID, UUID], Depends(actor)],
    ) -> Started:
        ip_hash = client_ip_hash(request, ip_key)
        return Started(
            investigation_id=guarded(
                lambda: service.start(scope(identity, uuid4()), case_id, key, ip_hash)
            )
        )

    @router.get("/investigations/{investigation_id}")
    def snapshot(
        investigation_id: UUID, identity: Annotated[tuple[UUID, UUID], Depends(actor)]
    ) -> Snapshot:
        row, _ = guarded(lambda: service.snapshot(scope(identity, investigation_id)))
        return Snapshot.model_validate(row)

    @router.post("/investigations/{investigation_id}/decision", status_code=202)
    def decide(
        investigation_id: UUID,
        decision: DecisionRequest,
        key: Key,
        identity: Annotated[tuple[UUID, UUID], Depends(actor)],
    ) -> Recorded:
        return Recorded(
            decision_id=guarded(
                lambda: service.decide(scope(identity, investigation_id), decision, key)
            )
        )

    def stream_scope(
        investigation_id: UUID,
        identity: Annotated[tuple[UUID, UUID], Depends(actor)],
    ) -> ToolScope:
        current = scope(identity, investigation_id)
        guarded(lambda: service.snapshot(current))
        return current

    @router.get(
        "/investigations/{investigation_id}/events",
        response_class=EventSourceResponse,
        openapi_extra={"x-sse-event-envelope": {"$ref": "#/components/schemas/InvestigationEvent"}},
    )
    async def events(
        request: Request,
        current_scope: Annotated[ToolScope, Depends(stream_scope)],
        last_event_id: Annotated[int, Header(ge=0, le=2**63 - 1)] = 0,
    ) -> AsyncIterator[ServerSentEvent]:
        cursor = last_event_id
        while not await request.is_disconnected():
            row, batch = await run_in_threadpool(
                guarded, lambda after=cursor: service.snapshot(current_scope, after)
            )
            for item in batch:
                cursor = item["sequence"]
                event = EVENTS.validate_python({"kind": item["kind"], "payload": item["payload"]})
                yield ServerSentEvent(id=str(cursor), event=event.kind, data=event.payload)
            if len(batch) < 50 and row["status"] in {"review", "complete", "failed"}:
                return
            await asyncio.sleep(0.5)

    return router
