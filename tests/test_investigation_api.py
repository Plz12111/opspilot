import asyncio
import json

from sqlalchemy import func, select

from opspilot.agent.graph import InvestigationRunner, RuleBasedDiagnosisSynthesizer
from opspilot.agent.models import Evidence
from opspilot.db.models import (
    EvidenceRecord,
    InvestigationJobRecord,
    RunEventRecord,
    ToolCallRecord,
)
from opspilot.domain.enums import InvestigationStatus
from opspilot.services.investigations import InvestigationService
from opspilot.tools.gateway import ToolGateway
from tests.fake_tools import AnyToolInput, fake_observation_gateway
from tests.test_alertmanager import alert_payload


async def test_investigation_api_persists_trace_and_evidence(client) -> None:
    alert = await client.post("/api/v1/webhooks/alertmanager", json=alert_payload())
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate?wait=true",
        json={"step_budget": 6},
    )

    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["steps_used"] == 5
    assert len(run["diagnosis"]["evidence_ids"]) == 5

    run_response = await client.get(f"/api/v1/runs/{run['id']}")
    incident_response = await client.get(f"/api/v1/incidents/{incident_id}")
    assert run_response.status_code == 200
    assert incident_response.json()["status"] == "DIAGNOSED"

    async with app.state.session_factory() as session:
        tool_calls = await session.scalar(select(func.count()).select_from(ToolCallRecord))
        evidence = await session.scalar(select(func.count()).select_from(EvidenceRecord))

    assert tool_calls == 5
    assert evidence == 5


async def test_investigation_api_returns_404_for_unknown_incident(client) -> None:
    response = await client.post(
        "/api/v1/incidents/inc-missing/investigate", json={"step_budget": 4}
    )

    assert response.status_code == 404


class RunbookOnlyTool:
    name = "search_runbooks"
    input_model = AnyToolInput

    async def run(self, arguments):
        return [
            Evidence(
                id="evd-runbook-only",
                source_type="runbook",
                source_uri="runbook://test#chunk=1",
                content="Restarting may mitigate the issue.",
            )
        ]


async def test_low_confidence_completed_run_requires_human(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="low-confidence"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = ToolGateway([RunbookOnlyTool()])

    run = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate?wait=true",
        json={"step_budget": 6},
    )
    incident = await client.get(f"/api/v1/incidents/{incident_id}")

    assert run.status_code == 201
    assert run.json()["status"] == "COMPLETED"
    assert run.json()["diagnosis"]["confidence"] == 0.5
    assert incident.json()["status"] == "NEEDS_HUMAN"


async def test_future_alert_timestamp_uses_valid_investigation_window(client) -> None:
    payload = alert_payload(fingerprint="future-clock-skew", starts_at="2099-01-01T00:00:00Z")
    alert = await client.post("/api/v1/webhooks/alertmanager", json=payload)
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()

    run = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate?wait=true",
        json={"step_budget": 6},
    )

    assert run.status_code == 201
    assert run.json()["status"] == "COMPLETED"


async def wait_for_terminal_run(client, run_id: str) -> dict:
    for _ in range(200):
        response = await client.get(f"/api/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] not in {"PENDING", "RUNNING"}:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach a terminal state")


class BlockingSynthesizer:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.delegate = RuleBasedDiagnosisSynthesizer()

    async def synthesize(self, state):
        self.started.set()
        await self.release.wait()
        return await self.delegate.synthesize(state)


class FailingSynthesizer:
    async def synthesize(self, state):
        raise RuntimeError("synthetic diagnosis failure")


async def test_investigation_returns_202_before_background_completion(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="async-investigation"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()
    synthesizer = BlockingSynthesizer()
    app.state.diagnosis_synthesizer = synthesizer

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate",
        json={"step_budget": 6},
    )

    assert response.status_code == 202
    assert response.json()["status"] in {"PENDING", "RUNNING"}
    await asyncio.wait_for(synthesizer.started.wait(), timeout=1)
    running = await client.get(f"/api/v1/runs/{response.json()['id']}")
    assert running.json()["status"] == "RUNNING"

    synthesizer.release.set()
    completed = await wait_for_terminal_run(client, response.json()["id"])
    assert completed["status"] == "COMPLETED"


async def test_investigation_idempotency_key_reuses_run(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="idempotent-investigation"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()
    headers = {"Idempotency-Key": "investigation-burst-key"}

    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/incidents/{incident_id}/investigate",
                headers=headers,
                json={"step_budget": 6},
            )
            for _ in range(20)
        )
    )
    run_ids = {response.json()["id"] for response in responses}

    assert {response.status_code for response in responses} == {202}
    assert len(run_ids) == 1
    completed = await wait_for_terminal_run(client, run_ids.pop())
    assert completed["status"] == "COMPLETED"


async def test_investigation_idempotency_key_cannot_cross_incidents(client) -> None:
    first = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="idempotency-incident-one"),
    )
    second = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="idempotency-incident-two"),
    )
    headers = {"Idempotency-Key": "cross-incident-key"}
    created = await client.post(
        f"/api/v1/incidents/{first.json()['incident_ids'][0]}/investigate",
        headers=headers,
        json={"step_budget": 1},
    )
    conflict = await client.post(
        f"/api/v1/incidents/{second.json()['incident_ids'][0]}/investigate",
        headers=headers,
        json={"step_budget": 1},
    )

    assert created.status_code == 202
    assert conflict.status_code == 409


async def test_run_events_are_ordered_and_sse_closes_on_terminal_event(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="ordered-events"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()

    run = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate?wait=true",
        json={"step_budget": 6},
    )
    stream = await client.get(f"/api/v1/runs/{run.json()['id']}/events")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]

    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["event_type"] == "run.queued"
    assert events[-1]["event_type"] == "run.completed"
    assert [event["event_type"] for event in events].count("tool.completed") == 5


async def test_failed_background_job_persists_terminal_event(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="failed-job"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()
    app.state.diagnosis_synthesizer = FailingSynthesizer()

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate",
        json={"step_budget": 6},
    )
    failed = await wait_for_terminal_run(client, response.json()["id"])

    assert failed["status"] == "FAILED"
    assert "synthetic diagnosis failure" in failed["error"]
    async with app.state.session_factory() as session:
        job = await session.scalar(
            select(InvestigationJobRecord).where(
                InvestigationJobRecord.run_id == response.json()["id"]
            )
        )
        event = await session.scalar(
            select(RunEventRecord)
            .where(RunEventRecord.run_id == response.json()["id"])
            .order_by(RunEventRecord.sequence.desc())
        )
    assert job is not None and job.status == InvestigationStatus.FAILED
    assert event is not None and event.event_type == "run.failed"


async def test_coordinator_recovers_persisted_pending_job(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="startup-recovery"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()
    async with app.state.session_factory() as session:
        service = InvestigationService(session, InvestigationRunner(app.state.tool_gateway))
        run = await service.create(incident_id, step_budget=6)

    recovered = await app.state.investigation_coordinator.recover()
    completed = await wait_for_terminal_run(client, run.id)

    assert recovered == 1
    assert completed["status"] == "COMPLETED"
