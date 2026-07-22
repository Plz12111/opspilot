from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.api.dependencies import get_session
from opspilot.db.models import ProposedActionRecord
from opspilot.domain.enums import ApprovalDecision
from opspilot.remediation.models import (
    ActionProposal,
    ActionView,
    ApprovalView,
    ExecutionView,
)
from opspilot.remediation.policy import ActionPolicyError
from opspilot.remediation.service import (
    RemediationConflictError,
    RemediationNotFoundError,
    RemediationService,
)

router = APIRouter(prefix="/api/v1/actions", tags=["remediation"])

ActorHeader = Annotated[str, Header(alias="X-Actor-Id", min_length=1, max_length=255)]


class DecisionRequest(BaseModel):
    comment: str = Field(default="", max_length=2000)


class DecisionResponse(BaseModel):
    action: ActionView
    approval: ApprovalView


class ExecutionResponse(BaseModel):
    action: ActionView
    execution: ExecutionView


def action_view(action: ProposedActionRecord) -> ActionView:
    return ActionView.model_validate(action, from_attributes=True)


def service_for(request: Request, session: AsyncSession) -> RemediationService:
    return RemediationService(
        session,
        request.app.state.remediation_executor,
        request.app.state.remediation_approvers,
        locks=request.app.state.remediation_locks,
    )


def translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RemediationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ActionPolicyError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("", response_model=ActionView, status_code=status.HTTP_201_CREATED)
async def propose_action(
    payload: ActionProposal,
    actor: ActorHeader,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionView:
    try:
        action = await service_for(request, session).propose(payload, actor)
    except (RemediationNotFoundError, RemediationConflictError, ActionPolicyError) as exc:
        raise translate_error(exc) from exc
    return action_view(action)


@router.get("/{action_id}", response_model=ActionView)
async def get_action(
    action_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionView:
    action = await session.get(ProposedActionRecord, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="action not found")
    return action_view(action)


async def decide_action(
    action_id: str,
    payload: DecisionRequest,
    actor: str,
    decision: ApprovalDecision,
    request: Request,
    session: AsyncSession,
) -> DecisionResponse:
    try:
        action, approval = await service_for(request, session).decide(
            action_id,
            actor,
            decision,
            payload.comment,
        )
    except (RemediationNotFoundError, RemediationConflictError) as exc:
        raise translate_error(exc) from exc
    return DecisionResponse(
        action=action_view(action),
        approval=ApprovalView.model_validate(approval, from_attributes=True),
    )


@router.post("/{action_id}/approve", response_model=DecisionResponse)
async def approve_action(
    action_id: str,
    payload: DecisionRequest,
    actor: ActorHeader,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DecisionResponse:
    return await decide_action(
        action_id,
        payload,
        actor,
        ApprovalDecision.APPROVED,
        request,
        session,
    )


@router.post("/{action_id}/reject", response_model=DecisionResponse)
async def reject_action(
    action_id: str,
    payload: DecisionRequest,
    actor: ActorHeader,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DecisionResponse:
    return await decide_action(
        action_id,
        payload,
        actor,
        ApprovalDecision.REJECTED,
        request,
        session,
    )


@router.post("/{action_id}/execute", response_model=ExecutionResponse)
async def execute_action(
    action_id: str,
    actor: ActorHeader,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExecutionResponse:
    try:
        action, execution = await service_for(request, session).execute(action_id, actor)
    except (RemediationNotFoundError, RemediationConflictError) as exc:
        raise translate_error(exc) from exc
    return ExecutionResponse(
        action=action_view(action),
        execution=ExecutionView.model_validate(execution, from_attributes=True),
    )
