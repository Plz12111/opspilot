from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.db.models import (
    ActionExecutionRecord,
    ApprovalRecord,
    IncidentRecord,
    ProposedActionRecord,
    utcnow,
)
from opspilot.domain.enums import ActionStatus, ApprovalDecision, IncidentStatus
from opspilot.remediation.executor import ActionExecutor
from opspilot.remediation.locks import ActionLockRegistry
from opspilot.remediation.models import ActionProposal
from opspilot.remediation.policy import ActionPolicy
from opspilot.services.incidents import new_id, stable_digest


class RemediationNotFoundError(LookupError):
    pass


class RemediationConflictError(ValueError):
    pass


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class RemediationService:
    def __init__(
        self,
        session: AsyncSession,
        executor: ActionExecutor,
        approvers: set[str],
        policy: ActionPolicy | None = None,
        locks: ActionLockRegistry | None = None,
    ) -> None:
        self.session = session
        self.executor = executor
        self.approvers = approvers
        self.policy = policy or ActionPolicy()
        self.locks = locks or ActionLockRegistry()

    async def propose(self, proposal: ActionProposal, requester: str) -> ProposedActionRecord:
        incident = await self.session.get(IncidentRecord, proposal.incident_id)
        if incident is None:
            raise RemediationNotFoundError("incident not found")
        if incident.status in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            raise RemediationConflictError("resolved incident cannot accept remediation actions")
        risk, parameters = self.policy.validate(proposal)
        idempotency_key = proposal.idempotency_key or stable_digest(
            {
                "incident_id": proposal.incident_id,
                "action_type": proposal.action_type,
                "environment": proposal.target_environment,
                "service": proposal.service,
                "parameters": parameters,
                "requester": requester,
            }
        )
        async with self.locks.hold(f"proposal:{idempotency_key}"):
            existing = await self.session.scalar(
                select(ProposedActionRecord).where(
                    ProposedActionRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing
            action = ProposedActionRecord(
                id=new_id("act"),
                incident_id=proposal.incident_id,
                action_type=proposal.action_type,
                target_environment=proposal.target_environment,
                service=proposal.service,
                parameters=parameters,
                risk=risk,
                status=ActionStatus.PENDING_APPROVAL,
                requester=requester,
                reason=proposal.reason,
                idempotency_key=idempotency_key,
                expires_at=utcnow() + timedelta(minutes=proposal.expires_in_minutes),
            )
            self.session.add(action)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                existing = await self.session.scalar(
                    select(ProposedActionRecord).where(
                        ProposedActionRecord.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return existing
            return action

    async def decide(
        self,
        action_id: str,
        approver: str,
        decision: ApprovalDecision,
        comment: str = "",
    ) -> tuple[ProposedActionRecord, ApprovalRecord]:
        async with self.locks.hold(f"decision:{action_id}"):
            return await self._decide_locked(action_id, approver, decision, comment)

    async def _decide_locked(
        self,
        action_id: str,
        approver: str,
        decision: ApprovalDecision,
        comment: str,
    ) -> tuple[ProposedActionRecord, ApprovalRecord]:
        action = await self.session.get(ProposedActionRecord, action_id)
        if action is None:
            raise RemediationNotFoundError("action not found")
        existing = await self.session.scalar(
            select(ApprovalRecord).where(ApprovalRecord.action_id == action.id)
        )
        if existing is not None:
            if existing.decision == decision and existing.approver == approver:
                return action, existing
            raise RemediationConflictError("action already has a different approval decision")
        if approver not in self.approvers:
            raise RemediationConflictError("actor is not authorized to approve remediation")
        if approver == action.requester:
            raise RemediationConflictError("requester cannot approve their own action")
        if action.status != ActionStatus.PENDING_APPROVAL:
            raise RemediationConflictError(f"action is in {action.status.value} state")
        if aware(action.expires_at) <= utcnow():
            action.status = ActionStatus.EXPIRED
            await self.session.commit()
            raise RemediationConflictError("action approval has expired")
        approval = ApprovalRecord(
            id=new_id("apr"),
            action_id=action.id,
            approver=approver,
            decision=decision,
            comment=comment[:2000],
        )
        action.status = (
            ActionStatus.APPROVED
            if decision == ApprovalDecision.APPROVED
            else ActionStatus.REJECTED
        )
        action.approved_at = utcnow() if decision == ApprovalDecision.APPROVED else None
        self.session.add(approval)
        await self.session.commit()
        return action, approval

    async def execute(
        self, action_id: str, executor_id: str
    ) -> tuple[ProposedActionRecord, ActionExecutionRecord]:
        async with self.locks.hold(f"execution:{action_id}"):
            return await self._execute_locked(action_id, executor_id)

    async def _execute_locked(
        self, action_id: str, executor_id: str
    ) -> tuple[ProposedActionRecord, ActionExecutionRecord]:
        action = await self.session.scalar(
            select(ProposedActionRecord)
            .where(ProposedActionRecord.id == action_id)
            .with_for_update()
        )
        if action is None:
            raise RemediationNotFoundError("action not found")
        existing = await self.session.scalar(
            select(ActionExecutionRecord).where(ActionExecutionRecord.action_id == action.id)
        )
        if existing is not None and action.status in {
            ActionStatus.EXECUTED,
            ActionStatus.FAILED,
        }:
            return action, existing
        if action.status != ActionStatus.APPROVED:
            raise RemediationConflictError("action must be approved before execution")

        execution = ActionExecutionRecord(
            id=new_id("exe"),
            action_id=action.id,
            executor=executor_id,
            status="RUNNING",
            output={},
        )
        action.status = ActionStatus.EXECUTING
        self.session.add(execution)
        await self.session.commit()
        try:
            output = await self.executor.execute(
                action.action_type,
                action.target_environment,
                action.service,
                action.parameters,
            )
            action.status = ActionStatus.EXECUTED
            action.executed_at = utcnow()
            execution.status = "SUCCESS"
            execution.output = output
            execution.ended_at = utcnow()
        except Exception as exc:
            action.status = ActionStatus.FAILED
            execution.status = "FAILED"
            execution.error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            execution.ended_at = utcnow()
        await self.session.commit()
        return action, execution
