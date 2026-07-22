from opspilot.integrations.feishu.notifier import FakeChatNotifier


async def test_fake_notifier_keeps_thread_reference() -> None:
    notifier = FakeChatNotifier()
    root = await notifier.publish_incident({"id": "inc-1", "status": "OPEN"})
    reply = await notifier.reply_progress(root, {"stage": "query_logs"})
    await notifier.update_incident(root, {"id": "inc-1", "status": "INVESTIGATING"})

    assert root.root_message_id == root.message_id
    assert reply.root_message_id == root.message_id
    assert len(notifier.published) == 1
    assert len(notifier.replies) == 1
    assert len(notifier.updated) == 1
