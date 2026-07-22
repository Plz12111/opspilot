from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx


def _check(response: httpx.Response) -> dict:
    response.raise_for_status()
    return response.json()


def load_runbooks() -> list[dict[str, str]]:
    module_path = Path(__file__).resolve()
    candidates = [
        module_path.parents[3] / "demo" / "runbooks",
        module_path.parents[2] / "demo" / "runbooks",
    ]
    runbook_dir = next((path for path in candidates if path.is_dir()), None)
    if runbook_dir is None:
        raise FileNotFoundError("packaged demo Runbooks were not found")
    runbooks = []
    for path in sorted(runbook_dir.glob("*.md")):
        service = path.stem.removesuffix("-service")
        runbooks.append(
            {
                "title": f"{service.title()} Service Runbook",
                "source_uri": f"demo://runbooks/{path.name}",
                "service": service,
                "environment": "demo",
                "content": path.read_text(),
            }
        )
    return runbooks


async def ingest_runbooks(client: httpx.AsyncClient) -> None:
    for runbook in load_runbooks():
        _check(
            await client.post(
                "/api/v1/runbooks",
                json=runbook,
            )
        )


async def seed_workflow(client: httpx.AsyncClient, base_url: str) -> dict:
    _check(await client.get("/health/ready"))
    await ingest_runbooks(client)
    started_at = datetime(2026, 1, 1, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    alert = _check(
        await client.post(
            "/api/v1/webhooks/alertmanager",
            json={
                "version": "4",
                "status": "firing",
                "receiver": "opspilot",
                "groupLabels": {"alertname": "InventoryHighLatency"},
                "commonLabels": {"environment": "demo", "service": "inventory"},
                "commonAnnotations": {},
                "externalURL": "http://alertmanager:9093",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": "InventoryHighLatency",
                            "environment": "demo",
                            "service": "inventory",
                            "severity": "P1",
                        },
                        "annotations": {
                            "summary": "Inventory p95 latency exceeds the demo SLO",
                            "description": "Gateway requests are delayed by inventory calls.",
                        },
                        "startsAt": started_at,
                        "endsAt": "0001-01-01T00:00:00Z",
                        "generatorURL": "http://prometheus:9090/graph",
                        "fingerprint": "opspilot-demo-inventory-latency-v1",
                    }
                ],
            },
        )
    )
    incident_id = alert["incident_ids"][0]
    workspace = _check(await client.get(f"/api/v1/incidents/{incident_id}/workspace"))
    completed = next(
        (run for run in workspace["runs"] if run["status"] in {"COMPLETED", "BUDGET_EXHAUSTED"}),
        None,
    )
    if completed is None:
        completed = _check(
            await client.post(
                f"/api/v1/incidents/{incident_id}/investigate?wait=true",
                headers={"Idempotency-Key": "demo-investigation-v1"},
                json={"step_budget": 6},
            )
        )
    action = _check(
        await client.post(
            "/api/v1/actions",
            headers={"X-Actor-Id": "demo-oncall"},
            json={
                "incident_id": incident_id,
                "action_type": "restart_service",
                "target_environment": "demo",
                "service": "inventory",
                "parameters": {"instances": 1},
                "reason": "Restart the demo inventory service after evidence review.",
                "expires_in_minutes": 60,
                "idempotency_key": "demo-inventory-restart-v1",
            },
        )
    )
    approval = _check(
        await client.post(
            f"/api/v1/actions/{action['id']}/approve",
            headers={"X-Actor-Id": "demo-approver"},
            json={"comment": "Approved for the isolated demo environment."},
        )
    )
    execution = _check(
        await client.post(
            f"/api/v1/actions/{action['id']}/execute",
            headers={"X-Actor-Id": "demo-worker"},
        )
    )
    return {
        "incident_id": incident_id,
        "run_id": completed["id"],
        "run_status": completed["status"],
        "action_id": action["id"],
        "approval": approval["approval"]["decision"],
        "execution": execution["execution"]["status"],
        "workspace_url": f"{base_url.rstrip('/')}/?incident={incident_id}",
    }


async def seed(base_url: str) -> dict:
    timeout = httpx.Timeout(60.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        return await seed_workflow(client, base_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a complete OpsPilot demo workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser("seed", help="seed one idempotent incident workflow")
    seed_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    result = asyncio.run(seed(args.base_url))
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
