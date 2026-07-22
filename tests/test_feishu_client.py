import json

import httpx

from opspilot.integrations.feishu.client import FeishuClient, TenantAccessTokenProvider


async def test_token_is_cached_and_card_content_is_serialized_once() -> None:
    token_calls = 0
    sent_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, sent_request
        if request.url.path.endswith("/tenant_access_token/internal"):
            token_calls += 1
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "token-1", "expire": 7200},
            )
        sent_request = request
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om-1"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://open.feishu.cn"
    ) as http_client:
        tokens = TenantAccessTokenProvider("app-id", "app-secret", http_client)
        client = FeishuClient(http_client, tokens)
        first_id = await client.send_card("oc-1", {"elements": [{"tag": "div"}]})
        second_id = await client.send_card("oc-1", {"elements": []})

    assert first_id == "om-1"
    assert second_id == "om-1"
    assert token_calls == 1
    assert sent_request is not None
    body = json.loads(sent_request.content)
    assert body["receive_id"] == "oc-1"
    assert isinstance(body["content"], str)
    assert json.loads(body["content"]) == {"elements": []}
    assert sent_request.headers["Authorization"] == "Bearer token-1"


async def test_invalid_token_is_refreshed_once() -> None:
    token_calls = 0
    message_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, message_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": f"token-{token_calls}",
                    "expire": 7200,
                },
            )
        message_calls += 1
        if message_calls == 1:
            return httpx.Response(200, json={"code": 99991663, "msg": "token expired"})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om-2"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://open.feishu.cn"
    ) as http_client:
        client = FeishuClient(
            http_client,
            TenantAccessTokenProvider("app-id", "app-secret", http_client),
        )
        message_id = await client.send_card("oc-1", {"elements": []})

    assert message_id == "om-2"
    assert token_calls == 2
    assert message_calls == 2
