from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.api.dependencies import get_session
from opspilot.db.models import (
    ActionExecutionRecord,
    AlertRecord,
    ApprovalRecord,
    EvidenceRecord,
    IncidentRecord,
    InvestigationRunRecord,
    ProposedActionRecord,
    RunbookDocumentRecord,
    RunEventRecord,
    ToolCallRecord,
)
from opspilot.domain.enums import (
    ActionRisk,
    ActionStatus,
    IncidentSeverity,
    IncidentStatus,
    InvestigationStatus,
    ToolExecutionStatus,
)

router = APIRouter(prefix="/api/v1", tags=["workspace"])


class DashboardSummary(BaseModel):
    active_incidents: int
    needs_human: int
    pending_approvals: int
    runbook_documents: int


class IncidentListItem(BaseModel):
    id: str
    title: str
    service: str
    environment: str
    severity: IncidentSeverity
    status: IncidentStatus
    alert_count: int
    started_at: datetime
    updated_at: datetime


class AlertView(BaseModel):
    id: str
    status: str
    labels: dict[str, Any]
    annotations: dict[str, Any]
    starts_at: datetime
    ends_at: datetime | None


class RunView(BaseModel):
    id: str
    status: InvestigationStatus
    step_budget: int
    steps_used: int
    diagnosis: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None


class ToolCallView(BaseModel):
    id: str
    run_id: str
    tool_name: str
    status: ToolExecutionStatus
    latency_ms: int
    error: str | None
    created_at: datetime


class EvidenceView(BaseModel):
    id: str
    run_id: str
    tool_call_id: str
    source_type: str
    source_uri: str
    content: str
    attributes: dict[str, Any]
    collected_at: datetime


class RunEventView(BaseModel):
    id: str
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class ApprovalSummary(BaseModel):
    approver: str
    decision: str
    comment: str
    decided_at: datetime


class ExecutionSummary(BaseModel):
    executor: str
    status: str
    output: dict[str, Any]
    error: str | None
    started_at: datetime
    ended_at: datetime | None


class ActionSummary(BaseModel):
    id: str
    action_type: str
    target_environment: str
    service: str
    parameters: dict[str, Any]
    risk: ActionRisk
    status: ActionStatus
    requester: str
    reason: str
    expires_at: datetime
    created_at: datetime
    approval: ApprovalSummary | None
    execution: ExecutionSummary | None


class IncidentWorkspace(BaseModel):
    incident: IncidentListItem
    alerts: list[AlertView]
    runs: list[RunView]
    run_events: list[RunEventView]
    tool_calls: list[ToolCallView]
    evidence: list[EvidenceView]
    actions: list[ActionSummary]


def from_record(model: type[BaseModel], record: Any):
    return model.model_validate(record, from_attributes=True)


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DashboardSummary:
    terminal = [IncidentStatus.RESOLVED, IncidentStatus.CLOSED, IncidentStatus.CANCELLED]
    active = await session.scalar(
        select(func.count())
        .select_from(IncidentRecord)
        .where(IncidentRecord.status.not_in(terminal))
    )
    needs_human = await session.scalar(
        select(func.count())
        .select_from(IncidentRecord)
        .where(IncidentRecord.status == IncidentStatus.NEEDS_HUMAN)
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(ProposedActionRecord)
        .where(ProposedActionRecord.status == ActionStatus.PENDING_APPROVAL)
    )
    runbooks = await session.scalar(select(func.count()).select_from(RunbookDocumentRecord))
    return DashboardSummary(
        active_incidents=active or 0,
        needs_human=needs_human or 0,
        pending_approvals=pending or 0,
        runbook_documents=runbooks or 0,
    )


@router.get("/incidents", response_model=list[IncidentListItem])
async def list_incidents(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IncidentListItem]:
    records = list(
        (
            await session.scalars(
                select(IncidentRecord).order_by(IncidentRecord.updated_at.desc()).limit(limit)
            )
        ).all()
    )
    return [from_record(IncidentListItem, record) for record in records]


@router.get("/incidents/{incident_id}/workspace", response_model=IncidentWorkspace)
async def get_incident_workspace(
    incident_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentWorkspace:
    incident = await session.get(IncidentRecord, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    alerts = list(
        (
            await session.scalars(
                select(AlertRecord)
                .where(AlertRecord.incident_id == incident_id)
                .order_by(AlertRecord.created_at.desc())
            )
        ).all()
    )
    runs = list(
        (
            await session.scalars(
                select(InvestigationRunRecord)
                .where(InvestigationRunRecord.incident_id == incident_id)
                .order_by(InvestigationRunRecord.created_at.desc())
            )
        ).all()
    )
    run_ids = [run.id for run in runs]
    tool_calls: list[ToolCallRecord] = []
    evidence: list[EvidenceRecord] = []
    run_events: list[RunEventRecord] = []
    if run_ids:
        run_events = list(
            (
                await session.scalars(
                    select(RunEventRecord)
                    .where(RunEventRecord.run_id.in_(run_ids))
                    .order_by(RunEventRecord.created_at, RunEventRecord.sequence)
                )
            ).all()
        )
        tool_calls = list(
            (
                await session.scalars(
                    select(ToolCallRecord)
                    .where(ToolCallRecord.run_id.in_(run_ids))
                    .order_by(ToolCallRecord.created_at)
                )
            ).all()
        )
        evidence = list(
            (
                await session.scalars(
                    select(EvidenceRecord)
                    .where(EvidenceRecord.run_id.in_(run_ids))
                    .order_by(EvidenceRecord.collected_at)
                )
            ).all()
        )
    actions = list(
        (
            await session.scalars(
                select(ProposedActionRecord)
                .where(ProposedActionRecord.incident_id == incident_id)
                .order_by(ProposedActionRecord.created_at.desc())
            )
        ).all()
    )
    action_ids = [action.id for action in actions]
    approvals: dict[str, ApprovalRecord] = {}
    executions: dict[str, ActionExecutionRecord] = {}
    if action_ids:
        approval_records = list(
            (
                await session.scalars(
                    select(ApprovalRecord).where(ApprovalRecord.action_id.in_(action_ids))
                )
            ).all()
        )
        execution_records = list(
            (
                await session.scalars(
                    select(ActionExecutionRecord).where(
                        ActionExecutionRecord.action_id.in_(action_ids)
                    )
                )
            ).all()
        )
        approvals = {record.action_id: record for record in approval_records}
        executions = {record.action_id: record for record in execution_records}
    action_views = []
    for action in actions:
        approval = approvals.get(action.id)
        execution = executions.get(action.id)
        action_views.append(
            ActionSummary(
                id=action.id,
                action_type=action.action_type,
                target_environment=action.target_environment,
                service=action.service,
                parameters=action.parameters,
                risk=action.risk,
                status=action.status,
                requester=action.requester,
                reason=action.reason,
                expires_at=action.expires_at,
                created_at=action.created_at,
                approval=(from_record(ApprovalSummary, approval) if approval is not None else None),
                execution=(
                    from_record(ExecutionSummary, execution) if execution is not None else None
                ),
            )
        )
    return IncidentWorkspace(
        incident=from_record(IncidentListItem, incident),
        alerts=[from_record(AlertView, record) for record in alerts],
        runs=[from_record(RunView, record) for record in runs],
        run_events=[from_record(RunEventView, record) for record in run_events],
        tool_calls=[from_record(ToolCallView, record) for record in tool_calls],
        evidence=[from_record(EvidenceView, record) for record in evidence],
        actions=action_views,
    )
