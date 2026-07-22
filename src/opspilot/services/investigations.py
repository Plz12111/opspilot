from __future__ import annotations

from datetime import UTC, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.agent.graph import InvestigationRunner
from opspilot.agent.models import InvestigationContext, InvestigationResult
from opspilot.db.models import (
    EvidenceRecord,
    IncidentRecord,
    InvestigationJobRecord,
    InvestigationRunRecord,
    OutboxRecord,
    RunEventRecord,
    ToolCallRecord,
    utcnow,
)
from opspilot.domain.enums import IncidentStatus, InvestigationStatus
from opspilot.services.incidents import new_id, stable_digest


class IncidentNotFoundError(LookupError):
    pass


class IncidentNotInvestigableError(ValueError):
    pass


class InvestigationIdempotencyConflictError(ValueError):
    pass


class InvestigationService:
    def __init__(self, session: AsyncSession, runner: InvestigationRunner) -> None:
        self.session = session
        self.runner = runner

    async def create(
        self,
        incident_id: str,
        step_budget: int = 6,
        idempotency_key: str | None = None,
    ) -> InvestigationRunRecord:
        if idempotency_key is not None:
            existing = await self._get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return self._validate_idempotent_run(existing, incident_id)
        incident = await self.session.get(IncidentRecord, incident_id)
        if incident is None:
            raise IncidentNotFoundError(incident_id)
        if incident.status in {
            IncidentStatus.RESOLVED,
            IncidentStatus.CLOSED,
            IncidentStatus.CANCELLED,
        }:
            raise IncidentNotInvestigableError(
                f"incident in {incident.status.value} state cannot start an investigation"
            )

        run = InvestigationRunRecord(
            id=new_id("run"),
            incident_id=incident.id,
            idempotency_key=idempotency_key,
            status=InvestigationStatus.PENDING,
            step_budget=step_budget,
            state={},
        )
        job = InvestigationJobRecord(
            id=new_id("job"),
            run_id=run.id,
            status=InvestigationStatus.PENDING,
        )
        incident.status = IncidentStatus.INVESTIGATING
        try:
            self.session.add(run)
            await self.session.flush()
            self.session.add(job)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            if idempotency_key is None:
                raise
            existing = await self._get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            return self._validate_idempotent_run(existing, incident_id)
        await self._emit_event(
            run.id,
            "run.queued",
            {"incident_id": incident.id, "step_budget": step_budget},
        )
        await self.session.refresh(run)
        return run

    async def _get_by_idempotency_key(self, key: str) -> InvestigationRunRecord | None:
        return await self.session.scalar(
            select(InvestigationRunRecord).where(InvestigationRunRecord.idempotency_key == key)
        )

    @staticmethod
    def _validate_idempotent_run(
        run: InvestigationRunRecord,
        incident_id: str,
    ) -> InvestigationRunRecord:
        if run.incident_id != incident_id:
            raise InvestigationIdempotencyConflictError(
                "idempotency key is already bound to another incident"
            )
        return run

    async def start(self, incident_id: str, step_budget: int = 6) -> InvestigationRunRecord:
        run = await self.create(incident_id, step_budget)
        return await self.execute(run.id)

    async def execute(self, run_id: str) -> InvestigationRunRecord:
        run = await self.session.get(InvestigationRunRecord, run_id)
        if run is None:
            raise LookupError(f"investigation run {run_id} not found")
        job = await self._get_job(run.id)
        if run.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.BUDGET_EXHAUSTED,
            InvestigationStatus.FAILED,
            InvestigationStatus.CANCELLED,
        }:
            if job is not None and job.status not in {
                InvestigationStatus.COMPLETED,
                InvestigationStatus.FAILED,
                InvestigationStatus.CANCELLED,
            }:
                job.status = (
                    InvestigationStatus.FAILED
                    if run.status == InvestigationStatus.FAILED
                    else InvestigationStatus.COMPLETED
                )
                job.completed_at = utcnow()
                await self.session.commit()
            return run

        incident = await self.session.get(IncidentRecord, run.incident_id)
        if incident is None:
            raise IncidentNotFoundError(run.incident_id)
        run.status = InvestigationStatus.RUNNING
        run.started_at = run.started_at or utcnow()
        if job is not None:
            job.status = InvestigationStatus.RUNNING
            job.attempts += 1
            job.locked_at = utcnow()
            job.last_error = None
        await self.session.commit()
        await self._emit_event(run.id, "run.started", {"attempt": job.attempts if job else 1})

        end_time = utcnow()
        incident_start = incident.started_at
        if incident_start.tzinfo is None:
            incident_start = incident_start.replace(tzinfo=UTC)
        if incident_start >= end_time:
            start_time = end_time - timedelta(minutes=5)
        else:
            start_time = max(incident_start, end_time - timedelta(hours=2))
        context = InvestigationContext(
            run_id=run.id,
            incident_id=incident.id,
            service=incident.service,
            environment=incident.environment,
            start_time=start_time,
            end_time=end_time,
            step_budget=run.step_budget,
        )
        try:
            self.runner.event_sink = lambda event_type, payload: self._emit_event(
                run.id, event_type, payload
            )
            result = await self.runner.run(context)
            await self._persist_result(run, incident, job, result)
            await self._emit_event(
                run.id,
                "run.completed",
                {
                    "status": result.status.value,
                    "steps_used": result.steps_used,
                    "evidence_count": len(result.evidence),
                },
            )
        except Exception as exc:
            await self.session.rollback()
            failed_run = await self.session.get(InvestigationRunRecord, run.id)
            if failed_run is not None:
                failed_run.status = InvestigationStatus.FAILED
                failed_run.error = f"{type(exc).__name__}: {str(exc)[:1000]}"
                failed_run.ended_at = utcnow()
                failed_incident = await self.session.get(IncidentRecord, incident.id)
                if failed_incident is not None:
                    failed_incident.status = IncidentStatus.NEEDS_HUMAN
                failed_job = await self._get_job(run.id)
                if failed_job is not None:
                    failed_job.status = InvestigationStatus.FAILED
                    failed_job.last_error = failed_run.error
                    failed_job.completed_at = utcnow()
                await self.session.commit()
                await self._emit_event(
                    run.id,
                    "run.failed",
                    {"error": failed_run.error},
                )
            raise
        await self.session.refresh(run)
        return run

    async def _get_job(self, run_id: str) -> InvestigationJobRecord | None:
        return await self.session.scalar(
            select(InvestigationJobRecord).where(InvestigationJobRecord.run_id == run_id)
        )

    async def _emit_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> RunEventRecord:
        latest = await self.session.scalar(
            select(func.max(RunEventRecord.sequence)).where(RunEventRecord.run_id == run_id)
        )
        event = RunEventRecord(
            id=new_id("evt"),
            run_id=run_id,
            sequence=(latest or 0) + 1,
            event_type=event_type,
            payload=payload,
        )
        self.session.add(event)
        await self.session.commit()
        return event

    async def _persist_result(
        self,
        run: InvestigationRunRecord,
        incident: IncidentRecord,
        job: InvestigationJobRecord | None,
        result: InvestigationResult,
    ) -> None:
        evidence_by_call = {
            evidence.id: execution.id
            for execution in result.executions
            for evidence in execution.evidence
        }
        for execution in result.executions:
            self.session.add(
                ToolCallRecord(
                    id=execution.id,
                    run_id=run.id,
                    tool_name=execution.request.name,
                    arguments=execution.request.arguments,
                    status=execution.status,
                    latency_ms=execution.latency_ms,
                    error=execution.error,
                    created_at=execution.started_at,
                )
            )
        await self.session.flush()
        for evidence in result.evidence:
            self.session.add(
                EvidenceRecord(
                    id=evidence.id,
                    run_id=run.id,
                    tool_call_id=evidence_by_call[evidence.id],
                    source_type=evidence.source_type,
                    source_uri=evidence.source_uri,
                    content=evidence.content,
                    attributes=evidence.attributes,
                    checksum=evidence.attributes.get("checksum") or stable_digest(evidence.content),
                    collected_at=evidence.collected_at,
                )
            )
        run.status = result.status
        run.steps_used = result.steps_used
        run.state = result.model_dump(mode="json", exclude={"diagnosis"})
        run.diagnosis = result.diagnosis.model_dump(mode="json")
        run.ended_at = utcnow()
        if job is not None:
            job.status = InvestigationStatus.COMPLETED
            job.completed_at = run.ended_at
        has_sufficient_diagnosis = (
            result.status == InvestigationStatus.COMPLETED
            and result.diagnosis.confidence >= 0.6
            and bool(result.diagnosis.evidence_ids)
        )
        incident.status = (
            IncidentStatus.DIAGNOSED if has_sufficient_diagnosis else IncidentStatus.NEEDS_HUMAN
        )
        self.session.add(
            OutboxRecord(
                id=new_id("out"),
                topic="incident.investigation_completed",
                idempotency_key=f"incident:{incident.id}:run:{run.id}:completed",
                payload={
                    "incident_id": incident.id,
                    "run_id": run.id,
                    "status": result.status.value,
                },
            )
        )
        await self.session.commit()
