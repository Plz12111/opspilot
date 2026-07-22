from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.db.models import ConversationBindingRecord, IncidentRecord, OutboxRecord, utcnow
from opspilot.domain.enums import OutboxStatus
from opspilot.integrations.feishu.notifier import ChatNotifier
from opspilot.services.incidents import new_id


class NotificationDispatcher:
    def __init__(self, session: AsyncSession, notifier: ChatNotifier) -> None:
        self.session = session
        self.notifier = notifier

    async def dispatch_one(self) -> bool:
        record = await self.session.scalar(
            select(OutboxRecord)
            .where(
                OutboxRecord.status == OutboxStatus.PENDING,
                OutboxRecord.topic.in_(
                    ["incident.created", "incident.alert_merged", "incident.resolved"]
                ),
            )
            .order_by(OutboxRecord.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if record is None:
            return False
        record.status = OutboxStatus.PROCESSING
        record.attempts += 1
        await self.session.flush()

        try:
            incident = await self.session.get(IncidentRecord, record.payload["incident_id"])
            if incident is None:
                raise LookupError(f"incident {record.payload['incident_id']} does not exist")
            view = {
                "id": incident.id,
                "title": incident.title,
                "severity": incident.severity.value,
                "status": incident.status.value,
                "service": incident.service,
                "environment": incident.environment,
                "alert_count": incident.alert_count,
            }
            binding = await self.session.scalar(
                select(ConversationBindingRecord).where(
                    ConversationBindingRecord.incident_id == incident.id,
                    ConversationBindingRecord.provider == "feishu",
                )
            )
            if binding is None:
                ref = await self.notifier.publish_incident(view)
                self.session.add(
                    ConversationBindingRecord(
                        id=new_id("bind"),
                        incident_id=incident.id,
                        provider=ref.provider,
                        tenant_key=ref.tenant_key,
                        chat_id=ref.chat_id,
                        root_message_id=ref.root_message_id,
                    )
                )
            else:
                from opspilot.integrations.feishu.notifier import MessageRef

                ref = MessageRef(
                    binding.provider,
                    binding.tenant_key,
                    binding.chat_id,
                    binding.root_message_id,
                    binding.root_message_id,
                )
                await self.notifier.update_incident(ref, view)
            record.status = OutboxStatus.SENT
            record.sent_at = utcnow()
            record.last_error = None
            await self.session.commit()
            return True
        except Exception as exc:
            await self.session.rollback()
            failed = await self.session.get(OutboxRecord, record.id)
            if failed is not None:
                failed.status = OutboxStatus.FAILED
                failed.last_error = str(exc)[:1000]
                await self.session.commit()
            raise
