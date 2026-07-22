from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.db.models import IntegrationEventRecord, OutboxRecord
from opspilot.services.incidents import new_id


@dataclass(frozen=True, slots=True)
class StoredEvent:
    event_id: str
    event_type: str
    tenant_key: str
    duplicate: bool


@dataclass(frozen=True, slots=True)
class CardActionEvent:
    action: str
    action_id: str
    actor: str
    comment: str


def event_metadata(body: dict[str, Any]) -> tuple[str, str, str]:
    header = body.get("header", {})
    event_id = str(header.get("event_id") or body.get("event_id") or "")
    event_type = str(header.get("event_type") or body.get("type") or "unknown")
    tenant_key = str(header.get("tenant_key") or body.get("tenant_key") or "default")
    if not event_id:
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        event_id = f"payload_{digest}"
    return event_id, event_type, tenant_key


async def store_event(session: AsyncSession, body: dict[str, Any]) -> StoredEvent:
    event_id, event_type, tenant_key = event_metadata(body)
    payload_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    record = IntegrationEventRecord(
        id=new_id("evt"),
        provider="feishu",
        tenant_key=tenant_key,
        event_id=event_id,
        event_type=event_type,
        payload=body,
        payload_digest=hashlib.sha256(payload_bytes).hexdigest(),
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return StoredEvent(event_id, event_type, tenant_key, duplicate=True)

    session.add(
        OutboxRecord(
            id=new_id("out"),
            topic="feishu.event.received",
            idempotency_key=f"feishu:{tenant_key}:{event_id}",
            payload={"integration_event_id": record.id, "event_type": event_type},
        )
    )
    await session.commit()
    return StoredEvent(event_id, event_type, tenant_key, duplicate=False)


def extract_card_action(body: dict[str, Any]) -> CardActionEvent | None:
    event = body.get("event") if isinstance(body.get("event"), dict) else body
    action_payload = event.get("action", {})
    value = action_payload.get("value", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    action_id = value.get("action_id")
    if not action or not action_id:
        return None
    operator = event.get("operator", {})
    operator_id = operator.get("operator_id", {}) if isinstance(operator, dict) else {}
    actor = (
        operator_id.get("open_id")
        or operator.get("open_id")
        or event.get("open_id")
        or body.get("open_id")
        or ""
    )
    if not actor:
        return None
    return CardActionEvent(
        action=str(action),
        action_id=str(action_id),
        actor=str(actor),
        comment=str(value.get("comment", ""))[:2000],
    )
