from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from opspilot.domain.enums import InvestigationStatus, ToolExecutionStatus


class Evidence(BaseModel):
    id: str
    source_type: str
    source_uri: str
    content: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolRequest(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecution(BaseModel):
    id: str
    request: ToolRequest
    status: ToolExecutionStatus
    started_at: datetime
    latency_ms: int = Field(ge=0)
    evidence: list[Evidence] = Field(default_factory=list)
    error: str | None = None


class RootCauseCandidate(BaseModel):
    label: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)


class Diagnosis(BaseModel):
    summary: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    root_causes: list[RootCauseCandidate] = Field(default_factory=list, max_length=3)
    suggested_actions: list[str] = Field(default_factory=list)


class InvestigationContext(BaseModel):
    run_id: str
    incident_id: str
    service: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    environment: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    start_time: datetime
    end_time: datetime
    step_budget: int = Field(default=6, ge=1, le=20)


class InvestigationResult(BaseModel):
    run_id: str
    incident_id: str
    status: InvestigationStatus
    plan: list[ToolRequest]
    executions: list[ToolExecution]
    evidence: list[Evidence]
    diagnosis: Diagnosis
    steps_used: int
