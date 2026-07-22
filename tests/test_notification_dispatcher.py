from sqlalchemy import func, select

from opspilot.db.models import ConversationBindingRecord, OutboxRecord
from opspilot.integrations.alertmanager.schemas import AlertmanagerWebhook
from opspilot.integrations.feishu.notifier import FakeChatNotifier
from opspilot.services.incidents import IncidentService
from opspilot.services.notifications import NotificationDispatcher
from tests.test_alertmanager import alert_payload


async def test_created_incident_is_published_once(client) -> None:
    app = client._transport.app
    async with app.state.session_factory() as session:
        webhook = AlertmanagerWebhook.model_validate(alert_payload())
        await IncidentService(session).ingest_alertmanager(webhook)

    notifier = FakeChatNotifier()
    async with app.state.session_factory() as session:
        dispatcher = NotificationDispatcher(session, notifier)
        assert await dispatcher.dispatch_one() is True
        assert await dispatcher.dispatch_one() is False

        bindings = await session.scalar(select(func.count()).select_from(ConversationBindingRecord))
        pending = await session.scalar(
            select(func.count()).select_from(OutboxRecord).where(OutboxRecord.status == "PENDING")
        )

    assert len(notifier.published) == 1
    assert bindings == 1
    assert pending == 0
