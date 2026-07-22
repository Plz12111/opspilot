from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from opspilot.integrations.feishu.client import FeishuClient


@dataclass(frozen=True, slots=True)
class MessageRef:
    provider: str
    tenant_key: str
    chat_id: str
    message_id: str
    root_message_id: str


class ChatNotifier(Protocol):
    async def publish_incident(self, incident: dict[str, Any]) -> MessageRef: ...

    async def reply_progress(self, ref: MessageRef, event: dict[str, Any]) -> MessageRef: ...

    async def update_incident(self, ref: MessageRef, incident: dict[str, Any]) -> None: ...


class FakeChatNotifier:
    def __init__(self, tenant_key: str = "test", chat_id: str = "test-chat") -> None:
        self.tenant_key = tenant_key
        self.chat_id = chat_id
        self.published: list[dict[str, Any]] = []
        self.replies: list[tuple[MessageRef, dict[str, Any]]] = []
        self.updated: list[tuple[MessageRef, dict[str, Any]]] = []

    async def publish_incident(self, incident: dict[str, Any]) -> MessageRef:
        self.published.append(incident)
        message_id = f"fake-message-{len(self.published)}"
        return MessageRef("feishu", self.tenant_key, self.chat_id, message_id, message_id)

    async def reply_progress(self, ref: MessageRef, event: dict[str, Any]) -> MessageRef:
        self.replies.append((ref, event))
        return MessageRef(
            "feishu",
            ref.tenant_key,
            ref.chat_id,
            f"fake-reply-{len(self.replies)}",
            ref.root_message_id,
        )

    async def update_incident(self, ref: MessageRef, incident: dict[str, Any]) -> None:
        self.updated.append((ref, incident))


def incident_card(incident: dict[str, Any]) -> dict[str, Any]:
    severity = str(incident.get("severity", "P2"))
    color = {"P0": "red", "P1": "orange", "P2": "yellow", "P3": "blue"}.get(severity, "grey")
    incident_id = str(incident["id"])
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text", "content": f"[{severity}] {incident['title']}"},
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"**事故**\n{incident_id}"},
                    },
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"**状态**\n{incident['status']}"},
                    },
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"**服务**\n{incident['service']}"},
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**环境**\n{incident['environment']}",
                        },
                    },
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "刷新"},
                        "type": "default",
                        "value": {
                            "action": "incident.refresh",
                            "incident_id": incident_id,
                            "card_version": incident.get("version", 1),
                        },
                    }
                ],
            },
        ],
    }


class FeishuChatNotifier:
    def __init__(self, client: FeishuClient, tenant_key: str, chat_id: str) -> None:
        self.client = client
        self.tenant_key = tenant_key
        self.chat_id = chat_id

    async def publish_incident(self, incident: dict[str, Any]) -> MessageRef:
        message_id = await self.client.send_card(self.chat_id, incident_card(incident))
        return MessageRef("feishu", self.tenant_key, self.chat_id, message_id, message_id)

    async def reply_progress(self, ref: MessageRef, event: dict[str, Any]) -> MessageRef:
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "markdown",
                    "content": str(event.get("summary", "调查状态已更新")),
                }
            ],
        }
        message_id = await self.client.reply_card(ref.message_id, card)
        return MessageRef("feishu", ref.tenant_key, ref.chat_id, message_id, ref.root_message_id)

    async def update_incident(self, ref: MessageRef, incident: dict[str, Any]) -> None:
        await self.client.update_card(ref.root_message_id, incident_card(incident))
