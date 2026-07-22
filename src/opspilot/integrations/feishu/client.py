from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


class FeishuAPIError(RuntimeError):
    def __init__(self, operation: str, code: int, message: str) -> None:
        super().__init__(f"Feishu {operation} failed: code={code}, message={message}")
        self.operation = operation
        self.code = code
        self.message = message


@dataclass(slots=True)
class CachedToken:
    value: str
    expires_at: float


class TenantAccessTokenProvider:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        client: httpx.AsyncClient,
        refresh_margin_seconds: int = 60,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.client = client
        self.refresh_margin_seconds = refresh_margin_seconds
        self._cached: CachedToken | None = None
        self._lock = asyncio.Lock()

    async def get(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._is_valid():
            return self._cached.value  # type: ignore[union-attr]
        async with self._lock:
            if not force_refresh and self._is_valid():
                return self._cached.value  # type: ignore[union-attr]
            response = await self.client.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            response.raise_for_status()
            payload = response.json()
            code = int(payload.get("code", -1))
            if code != 0:
                raise FeishuAPIError("get_tenant_access_token", code, payload.get("msg", ""))
            token = str(payload["tenant_access_token"])
            expires_in = max(int(payload.get("expire", 7200)), self.refresh_margin_seconds + 1)
            self._cached = CachedToken(token, time.monotonic() + expires_in)
            return token

    def invalidate(self) -> None:
        self._cached = None

    def _is_valid(self) -> bool:
        return bool(
            self._cached
            and self._cached.expires_at - self.refresh_margin_seconds > time.monotonic()
        )


class FeishuClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        token_provider: TenantAccessTokenProvider,
    ) -> None:
        self.client = client
        self.token_provider = token_provider

    async def send_card(self, chat_id: str, card: dict[str, Any]) -> str:
        payload = await self._request(
            "send_message",
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            },
        )
        return str(payload["data"]["message_id"])

    async def reply_card(self, message_id: str, card: dict[str, Any]) -> str:
        payload = await self._request(
            "reply_message",
            "POST",
            f"/open-apis/im/v1/messages/{message_id}/reply",
            json={
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            },
        )
        return str(payload["data"]["message_id"])

    async def update_card(self, message_id: str, card: dict[str, Any]) -> None:
        await self._request(
            "update_message",
            "PATCH",
            f"/open-apis/im/v1/messages/{message_id}",
            json={"content": json.dumps(card, ensure_ascii=False, separators=(",", ":"))},
        )

    async def _request(
        self,
        operation: str,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        for attempt in range(2):
            token = await self.token_provider.get(force_refresh=attempt == 1)
            headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
            response = await self.client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            payload = response.json()
            code = int(payload.get("code", -1))
            if code == 0:
                return payload
            if attempt == 0 and code in {99991661, 99991663, 99991668}:
                self.token_provider.invalidate()
                continue
            raise FeishuAPIError(operation, code, payload.get("msg", ""))
        raise FeishuAPIError(operation, -1, "token refresh retry exhausted")
