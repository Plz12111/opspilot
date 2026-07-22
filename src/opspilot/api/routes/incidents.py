from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.agent.graph import InvestigationRunner
from opspilot.api.dependencies import get_session
from opspilot.db.models import IncidentRecord, InvestigationRunRecord, RunEventRecord
from opspilot.domain.enums import IncidentSeverity, IncidentStatus, InvestigationStatus
from opspilot.services.investigations import (
    IncidentNotFoundError,
    IncidentNotInvestigableError,
    InvestigationIdempotencyConflictError,
    InvestigationService,
)

router = APIRouter(prefix="/api/v1", tags=["incidents"])


class StartInvestigationRequest(BaseModel):
    step_budget: int = Field(default=6, ge=1, le=20)


class IncidentView(BaseModel):
    id: str
    title: str
    service: str
    environment: str
    severity: IncidentSeverity
    status: IncidentStatus
    alert_count: int
    started_at: datetime
    resolved_at: datetime | None


class InvestigationRunView(BaseModel):
    id: str
    incident_id: str
    status: InvestigationStatus
    step_budget: int
    steps_used: int
    diagnosis: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None


def incident_view(record: IncidentRecord) -> IncidentView:
    return IncidentView.model_validate(record, from_attributes=True)


def run_view(record: InvestigationRunRecord) -> InvestigationRunView:
    return InvestigationRunView.model_validate(record, from_attributes=True)


@router.get("/incidents/{incident_id}", response_model=IncidentView)
async def get_incident(
    incident_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentView:
    incident = await session.get(IncidentRecord, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return incident_view(incident)


@router.post(
    "/incidents/{incident_id}/investigate",
    response_model=InvestigationRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_investigation(
    incident_id: str,
    payload: StartInvestigationRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    wait: Annotated[bool, Query()] = False,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=255),
    ] = None,
) -> InvestigationRunView:
    runner = InvestigationRunner(
        request.app.state.tool_gateway,
        request.app.state.diagnosis_synthesizer,
    )
    service = InvestigationService(session, runner)
    try:
        run = await service.create(incident_id, payload.step_budget, idempotency_key)
    except IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="incident not found",
        ) from exc
    except (IncidentNotInvestigableError, InvestigationIdempotencyConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    request.app.state.investigation_coordinator.schedule(run.id)
    if wait:
        await request.app.state.investigation_coordinator.wait(run.id)
        await session.refresh(run)
        response.status_code = status.HTTP_201_CREATED
    return run_view(run)


@router.get("/runs/{run_id}", response_model=InvestigationRunView)
async def get_investigation_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InvestigationRunView:
    run = await session.get(InvestigationRunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run_view(run)


@router.get("/runs/{run_id}/events")
async def stream_investigation_events(
    run_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    run = await session.get(InvestigationRunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    header_cursor = request.headers.get("last-event-id", "0")
    try:
        cursor = max(after, int(header_cursor))
    except ValueError:
        cursor = after

    async def event_stream() -> AsyncIterator[str]:
        nonlocal cursor
        terminal_types = {"run.completed", "run.failed", "run.cancelled"}
        while True:
            async with request.app.state.session_factory() as event_session:
                events = list(
                    (
                        await event_session.scalars(
                            select(RunEventRecord)
                            .where(
                                RunEventRecord.run_id == run_id,
                                RunEventRecord.sequence > cursor,
                            )
                            .order_by(RunEventRecord.sequence)
                        )
                    ).all()
                )
                current_run = await event_session.get(InvestigationRunRecord, run_id)
            for event in events:
                cursor = event.sequence
                data = json.dumps(
                    {
                        "id": event.id,
                        "run_id": event.run_id,
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "payload": event.payload,
                        "created_at": event.created_at.isoformat(),
                    },
                    separators=(",", ":"),
                )
                yield f"id: {event.sequence}\ndata: {data}\n\n"
                if event.event_type in terminal_types:
                    return
            if current_run is None or current_run.status in {
                InvestigationStatus.COMPLETED,
                InvestigationStatus.BUDGET_EXHAUSTED,
                InvestigationStatus.FAILED,
                InvestigationStatus.CANCELLED,
            }:
                return
            await asyncio.sleep(0.15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
