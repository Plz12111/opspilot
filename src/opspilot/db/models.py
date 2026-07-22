from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from opspilot.domain.enums import (
    ActionRisk,
    ActionStatus,
    ApprovalDecision,
    IncidentSeverity,
    IncidentStatus,
    InvestigationStatus,
    OutboxStatus,
    ToolExecutionStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class IncidentRecord(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    active_dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    severity: Mapped[IncidentSeverity] = mapped_column(Enum(IncidentSeverity))
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.OPEN, index=True
    )
    alert_count: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    alerts: Mapped[list[AlertRecord]] = relationship(back_populates="incident")


class AlertRecord(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_alert_source_external"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32))
    labels: Mapped[dict[str, Any]] = mapped_column(JSON)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[IncidentRecord] = relationship(back_populates="alerts")


class IntegrationEventRecord(Base):
    __tablename__ = "integration_events"
    __table_args__ = (
        UniqueConstraint("provider", "tenant_key", "event_id", name="uq_integration_event"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    tenant_key: Mapped[str] = mapped_column(String(128), default="default")
    event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_digest: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxRecord(Base):
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus), default=OutboxStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationBindingRecord(Base):
    __tablename__ = "conversation_bindings"
    __table_args__ = (
        UniqueConstraint("provider", "tenant_key", "incident_id", name="uq_incident_conversation"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    tenant_key: Mapped[str] = mapped_column(String(128), default="default")
    chat_id: Mapped[str] = mapped_column(String(255))
    root_message_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvestigationRunRecord(Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_investigation_run_idempotency"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[InvestigationStatus] = mapped_column(
        Enum(InvestigationStatus), default=InvestigationStatus.PENDING, index=True
    )
    step_budget: Mapped[int] = mapped_column(Integer)
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestigationJobRecord(Base):
    __tablename__ = "investigation_jobs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_investigation_job_run"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    status: Mapped[InvestigationStatus] = mapped_column(
        Enum(InvestigationStatus), default=InvestigationStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RunEventRecord(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[ToolExecutionStatus] = mapped_column(Enum(ToolExecutionStatus), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    tool_call_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_uri: Mapped[str] = mapped_column(String(1000))
    content: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunbookDocumentRecord(Base):
    __tablename__ = "runbook_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(String(1000), unique=True)
    service: Mapped[str | None] = mapped_column(String(128), index=True)
    environment: Mapped[str | None] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RunbookChunkRecord(Base):
    __tablename__ = "runbook_chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal", name="uq_runbook_chunk_ordinal"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("runbook_documents.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProposedActionRecord(Base):
    __tablename__ = "proposed_actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    target_environment: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk: Mapped[ActionRisk] = mapped_column(Enum(ActionRisk))
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus), default=ActionStatus.PENDING_APPROVAL, index=True
    )
    requester: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("action_id", name="uq_approval_action"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("proposed_actions.id"), index=True)
    approver: Mapped[str] = mapped_column(String(255))
    decision: Mapped[ApprovalDecision] = mapped_column(Enum(ApprovalDecision))
    comment: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionExecutionRecord(Base):
    __tablename__ = "action_executions"
    __table_args__ = (UniqueConstraint("action_id", name="uq_execution_action"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("proposed_actions.id"), index=True)
    executor: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_incident_service_status", IncidentRecord.service, IncidentRecord.status)
