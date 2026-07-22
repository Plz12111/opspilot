from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.db.models import AlertRecord, IncidentRecord, OutboxRecord, utcnow
from opspilot.domain.enums import IncidentSeverity, IncidentStatus
from opspilot.integrations.alertmanager.schemas import AlertmanagerAlert, AlertmanagerWebhook


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def stable_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize_severity(value: str | None) -> IncidentSeverity:
    normalized = (value or "P2").upper()
    aliases = {"CRITICAL": "P0", "HIGH": "P1", "WARNING": "P2", "INFO": "P3"}
    normalized = aliases.get(normalized, normalized)
    try:
        return IncidentSeverity(normalized)
    except ValueError:
        return IncidentSeverity.P2


def alert_fingerprint(alert: AlertmanagerAlert) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    identity_labels = {
        key: value
        for key, value in alert.labels.items()
        if key not in {"instance", "pod", "container"}
    }
    return stable_digest(identity_labels)[:32]


def active_dedupe_key(alert: AlertmanagerAlert) -> str:
    labels = alert.labels
    return ":".join(
        [
            "alertmanager",
            labels.get("environment", labels.get("env", "unknown")),
            labels.get("service", labels.get("job", "unknown")),
            labels.get("alertname", "unknown"),
            alert_fingerprint(alert),
        ]
    )


@dataclass(slots=True)
class IngestSummary:
    accepted: int = 0
    created: int = 0
    merged: int = 0
    duplicate_events: int = 0
    incident_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.incident_ids is None:
            self.incident_ids = []


class IncidentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest_alertmanager(self, webhook: AlertmanagerWebhook) -> IngestSummary:
        for attempt in range(3):
            try:
                return await self._ingest_once(webhook)
            except IntegrityError:
                await self.session.rollback()
                if attempt == 2:
                    raise
                await asyncio.sleep(0)
        raise RuntimeError("unreachable alert ingestion retry state")

    async def _ingest_once(self, webhook: AlertmanagerWebhook) -> IngestSummary:
        summary = IngestSummary()
        for alert in webhook.alerts:
            summary.accepted += 1
            external_id = self._external_alert_id(alert)
            existing_alert = await self.session.scalar(
                select(AlertRecord).where(
                    AlertRecord.source == "alertmanager",
                    AlertRecord.external_id == external_id,
                )
            )
            if existing_alert is not None:
                summary.duplicate_events += 1
                if existing_alert.incident_id not in summary.incident_ids:
                    summary.incident_ids.append(existing_alert.incident_id)
                continue

            key = active_dedupe_key(alert)
            incident = await self.session.scalar(
                select(IncidentRecord).where(IncidentRecord.active_dedupe_key == key)
            )
            if incident is None:
                incident = self._new_incident(alert, key)
                self.session.add(incident)
                await self.session.flush()
                summary.created += 1
                self.session.add(
                    OutboxRecord(
                        id=new_id("out"),
                        topic="incident.created",
                        idempotency_key=f"incident:{incident.id}:created",
                        payload={"incident_id": incident.id},
                    )
                )
            else:
                alert_count = await self.session.scalar(
                    update(IncidentRecord)
                    .where(IncidentRecord.id == incident.id)
                    .values(
                        alert_count=IncidentRecord.alert_count + 1,
                        updated_at=utcnow(),
                    )
                    .returning(IncidentRecord.alert_count)
                )
                summary.merged += 1
                self.session.add(
                    OutboxRecord(
                        id=new_id("out"),
                        topic="incident.alert_merged",
                        idempotency_key=f"incident:{incident.id}:alert:{external_id}",
                        payload={"incident_id": incident.id, "alert_count": alert_count},
                    )
                )

            if alert.status.lower() == "resolved":
                incident.status = IncidentStatus.RESOLVED
                incident.active_dedupe_key = None
                incident.resolved_at = alert.ends_at or utcnow()
                self.session.add(
                    OutboxRecord(
                        id=new_id("out"),
                        topic="incident.resolved",
                        idempotency_key=f"incident:{incident.id}:resolved:{external_id}",
                        payload={"incident_id": incident.id},
                    )
                )

            self.session.add(self._new_alert(alert, incident.id, external_id))
            summary.incident_ids.append(incident.id)

        await self.session.commit()
        return summary

    @staticmethod
    def _external_alert_id(alert: AlertmanagerAlert) -> str:
        return stable_digest(
            {
                "fingerprint": alert_fingerprint(alert),
                "starts_at": alert.starts_at.isoformat(),
                "status": alert.status,
            }
        )

    @staticmethod
    def _new_incident(alert: AlertmanagerAlert, key: str) -> IncidentRecord:
        labels = alert.labels
        annotations = alert.annotations
        return IncidentRecord(
            id=new_id("inc"),
            fingerprint=alert_fingerprint(alert),
            active_dedupe_key=key,
            severity=normalize_severity(labels.get("severity")),
            service=labels.get("service", labels.get("job", "unknown")),
            environment=labels.get("environment", labels.get("env", "unknown")),
            title=annotations.get("summary", labels.get("alertname", "Untitled alert"))[:255],
            status=IncidentStatus.OPEN,
            started_at=alert.starts_at,
        )

    @staticmethod
    def _new_alert(alert: AlertmanagerAlert, incident_id: str, external_id: str) -> AlertRecord:
        return AlertRecord(
            id=new_id("alt"),
            incident_id=incident_id,
            source="alertmanager",
            external_id=external_id,
            fingerprint=alert_fingerprint(alert),
            status=alert.status,
            labels=alert.labels,
            annotations=alert.annotations,
            raw_payload=alert.model_dump(mode="json", by_alias=True),
            starts_at=alert.starts_at,
            ends_at=alert.ends_at,
        )
