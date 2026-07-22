import hashlib
import json
import time

import httpx

from tests.test_remediation import create_incident, restart_payload


async def test_url_verification(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/integrations/feishu/events",
        json={"type": "url_verification", "token": "test-token", "challenge": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "hello"}


async def test_invalid_verification_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/integrations/feishu/events",
        json={"type": "url_verification", "token": "wrong", "challenge": "hello"},
    )

    assert response.status_code == 401


async def test_event_delivery_is_idempotent(client: httpx.AsyncClient) -> None:
    payload = {
        "schema": "2.0",
        "header": {
            "event_id": "evt-001",
            "event_type": "im.message.receive_v1",
            "tenant_key": "tenant-001",
            "token": "test-token",
        },
        "event": {"message": {"message_id": "om-001", "message_type": "text"}},
    }

    first = await client.post("/api/v1/integrations/feishu/events", json=payload)
    second = await client.post("/api/v1/integrations/feishu/events", json=payload)

    assert first.status_code == 200
    assert first.json() == {"code": 0, "duplicate": False}
    assert second.status_code == 200
    assert second.json() == {"code": 0, "duplicate": True}


async def test_signature_is_required_when_encrypt_key_is_configured(tmp_path) -> None:
    from opspilot.config import Settings
    from opspilot.main import create_app

    app = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'signed.db'}",
            db_auto_create=True,
            feishu_verification_token="test-token",
            feishu_encrypt_key="encrypt-key",
        )
    )
    payload = {
        "schema": "2.0",
        "header": {
            "event_id": "evt-signed",
            "event_type": "im.message.receive_v1",
            "tenant_key": "tenant-001",
            "token": "test-token",
        },
        "event": {},
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    nonce = "nonce-1"
    signature = hashlib.sha256(
        timestamp.encode() + nonce.encode() + b"encrypt-key" + raw_body
    ).hexdigest()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as signed_client:
            missing = await signed_client.post(
                "/api/v1/integrations/feishu/events", content=raw_body
            )
            accepted = await signed_client.post(
                "/api/v1/integrations/feishu/events",
                content=raw_body,
                headers={
                    "content-type": "application/json",
                    "X-Lark-Request-Timestamp": timestamp,
                    "X-Lark-Request-Nonce": nonce,
                    "X-Lark-Signature": signature,
                },
            )

    assert missing.status_code == 401
    assert accepted.status_code == 200


async def test_feishu_card_action_approves_remediation_idempotently(client) -> None:
    incident_id = await create_incident(client, "feishu-card-approval")
    proposed = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "investigator"},
        json=restart_payload(incident_id),
    )
    action_id = proposed.json()["id"]
    payload = {
        "schema": "2.0",
        "header": {
            "event_id": "evt-card-approval",
            "event_type": "card.action.trigger",
            "tenant_key": "tenant-001",
            "token": "test-token",
        },
        "event": {
            "operator": {"operator_id": {"open_id": "demo-approver"}},
            "action": {
                "value": {
                    "action": "remediation.approve",
                    "action_id": action_id,
                    "comment": "Approved from Feishu test card.",
                }
            },
        },
    }

    first = await client.post("/api/v1/integrations/feishu/card-actions", json=payload)
    repeated = await client.post("/api/v1/integrations/feishu/card-actions", json=payload)
    current = await client.get(f"/api/v1/actions/{action_id}")

    assert first.status_code == 200
    assert first.json()["action_status"] == "APPROVED"
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["action_status"] == "APPROVED"
    assert current.json()["status"] == "APPROVED"
