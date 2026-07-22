from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opspilot.domain.enums import ActionRisk, ActionStatus, ApprovalDecision


class RestartServiceParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instances: int = Field(default=1, ge=1, le=10)


class RollbackDeploymentParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_version: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")


class ActionProposal(BaseModel):
    incident_id: str
    action_type: str
    target_environment: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    service: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=10, max_length=2000)
    expires_in_minutes: int = Field(default=15, ge=1, le=60)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=255)


class ActionView(BaseModel):
    id: str
    incident_id: str
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
    approved_at: datetime | None
    executed_at: datetime | None


class ApprovalView(BaseModel):
    id: str
    action_id: str
    approver: str
    decision: ApprovalDecision
    comment: str
    decided_at: datetime


class ExecutionView(BaseModel):
    id: str
    action_id: str
    executor: str
    status: str
    output: dict[str, Any]
    error: str | None
    started_at: datetime
    ended_at: datetime | None
