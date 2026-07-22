import asyncio
from datetime import timedelta

from opspilot.db.models import ProposedActionRecord, utcnow
from tests.test_alertmanager import alert_payload


async def create_incident(client, fingerprint: str) -> str:
    response = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint=fingerprint),
    )
    return response.json()["incident_ids"][0]


def restart_payload(incident_id: str, environment: str = "demo") -> dict:
    return {
        "incident_id": incident_id,
        "action_type": "restart_service",
        "target_environment": environment,
        "service": "inventory-service",
        "parameters": {"instances": 1},
        "reason": "Restart one demo instance to mitigate the active incident.",
        "expires_in_minutes": 15,
        "idempotency_key": f"restart-{incident_id}",
    }


async def test_action_requires_approval_and_executes_exactly_once(client) -> None:
    incident_id = await create_incident(client, "remediation-happy-path")
    proposed = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "investigator"},
        json=restart_payload(incident_id),
    )
    action_id = proposed.json()["id"]

    before_approval = await client.post(
        f"/api/v1/actions/{action_id}/execute",
        headers={"X-Actor-Id": "worker"},
    )
    approved = await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "demo-approver"},
        json={"comment": "Approved for the demo environment."},
    )
    first_execution = await client.post(
        f"/api/v1/actions/{action_id}/execute",
        headers={"X-Actor-Id": "worker"},
    )
    repeated_execution = await client.post(
        f"/api/v1/actions/{action_id}/execute",
        headers={"X-Actor-Id": "worker"},
    )

    assert proposed.status_code == 201
    assert proposed.json()["status"] == "PENDING_APPROVAL"
    assert before_approval.status_code == 409
    assert approved.status_code == 200
    assert approved.json()["action"]["status"] == "APPROVED"
    assert first_execution.status_code == 200
    assert first_execution.json()["action"]["status"] == "EXECUTED"
    assert repeated_execution.json()["execution"]["id"] == first_execution.json()["execution"]["id"]
    assert len(client._transport.app.state.remediation_executor.executions) == 1


async def test_concurrent_execution_requests_share_one_execution(client) -> None:
    incident_id = await create_incident(client, "remediation-concurrent")
    proposed = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "investigator"},
        json=restart_payload(incident_id),
    )
    action_id = proposed.json()["id"]
    await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "demo-approver"},
        json={},
    )

    first, second = await asyncio.gather(
        client.post(
            f"/api/v1/actions/{action_id}/execute",
            headers={"X-Actor-Id": "worker-1"},
        ),
        client.post(
            f"/api/v1/actions/{action_id}/execute",
            headers={"X-Actor-Id": "worker-2"},
        ),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["execution"]["id"] == second.json()["execution"]["id"]
    assert len(client._transport.app.state.remediation_executor.executions) == 1


async def test_action_proposal_and_approval_are_idempotent(client) -> None:
    incident_id = await create_incident(client, "remediation-idempotent")
    payload = restart_payload(incident_id)
    first = await client.post(
        "/api/v1/actions", headers={"X-Actor-Id": "investigator"}, json=payload
    )
    second = await client.post(
        "/api/v1/actions", headers={"X-Actor-Id": "investigator"}, json=payload
    )
    action_id = first.json()["id"]
    approval = await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "demo-approver"},
        json={},
    )
    repeated_approval = await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "demo-approver"},
        json={},
    )

    assert second.json()["id"] == first.json()["id"]
    assert repeated_approval.json()["approval"]["id"] == approval.json()["approval"]["id"]


async def test_policy_rejects_production_and_unknown_actions(client) -> None:
    incident_id = await create_incident(client, "remediation-policy")
    production = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "investigator"},
        json=restart_payload(incident_id, environment="production"),
    )
    unknown_payload = restart_payload(incident_id)
    unknown_payload["action_type"] = "run_shell"
    unknown_payload["idempotency_key"] = "unknown-action-key"
    unknown = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "investigator"},
        json=unknown_payload,
    )

    assert production.status_code == 422
    assert unknown.status_code == 422


async def test_requester_and_unknown_actor_cannot_approve(client) -> None:
    incident_id = await create_incident(client, "remediation-separation")
    action = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "demo-approver"},
        json=restart_payload(incident_id),
    )
    action_id = action.json()["id"]
    self_approval = await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "demo-approver"},
        json={},
    )
    unknown_actor = await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "untrusted-user"},
        json={},
    )

    assert self_approval.status_code == 409
    assert unknown_actor.status_code == 409


async def test_expired_action_cannot_be_approved(client) -> None:
    incident_id = await create_incident(client, "remediation-expired")
    action = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "investigator"},
        json=restart_payload(incident_id),
    )
    action_id = action.json()["id"]
    app = client._transport.app
    async with app.state.session_factory() as session:
        record = await session.get(ProposedActionRecord, action_id)
        record.expires_at = utcnow() - timedelta(minutes=1)
        await session.commit()

    approval = await client.post(
        f"/api/v1/actions/{action_id}/approve",
        headers={"X-Actor-Id": "demo-approver"},
        json={},
    )
    current = await client.get(f"/api/v1/actions/{action_id}")

    assert approval.status_code == 409
    assert current.json()["status"] == "EXPIRED"
