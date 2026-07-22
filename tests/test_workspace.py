from tests.fake_tools import fake_observation_gateway
from tests.test_alertmanager import alert_payload
from tests.test_remediation import restart_payload


async def test_dashboard_static_assets_are_served(client) -> None:
    index = await client.get("/")
    styles = await client.get("/assets/styles.css")
    script = await client.get("/assets/app.js")

    assert index.status_code == 200
    assert "OpsPilot" in index.text
    assert "Incident Workspace" in index.text
    assert styles.status_code == 200
    assert "workspace" in styles.text
    assert script.status_code == 200
    assert "loadIncidents" in script.text
    assert "loadEvaluation" in script.text
    assert ".get('incident')" in script.text
    assert "Agent baseline comparison" in index.text


async def test_incident_workspace_aggregates_runs_evidence_and_actions(client) -> None:
    alert = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(fingerprint="workspace-aggregate"),
    )
    incident_id = alert.json()["incident_ids"][0]
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()
    await client.post(
        f"/api/v1/incidents/{incident_id}/investigate?wait=true",
        json={"step_budget": 6},
    )
    action = await client.post(
        "/api/v1/actions",
        headers={"X-Actor-Id": "dashboard-user"},
        json=restart_payload(incident_id),
    )

    summary = await client.get("/api/v1/dashboard/summary")
    incidents = await client.get("/api/v1/incidents")
    workspace = await client.get(f"/api/v1/incidents/{incident_id}/workspace")

    assert summary.status_code == 200
    assert summary.json()["active_incidents"] == 1
    assert summary.json()["pending_approvals"] == 1
    assert incidents.status_code == 200
    assert incidents.json()[0]["id"] == incident_id
    assert workspace.status_code == 200
    payload = workspace.json()
    assert payload["incident"]["id"] == incident_id
    assert len(payload["runs"]) == 1
    assert payload["run_events"][0]["event_type"] == "run.queued"
    assert payload["run_events"][-1]["event_type"] == "run.completed"
    assert len(payload["tool_calls"]) == 5
    assert len(payload["evidence"]) == 5
    assert payload["actions"][0]["id"] == action.json()["id"]
    assert payload["actions"][0]["approval"] is None


async def test_workspace_returns_404_for_unknown_incident(client) -> None:
    response = await client.get("/api/v1/incidents/inc-missing/workspace")

    assert response.status_code == 404
