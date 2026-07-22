import asyncio

import httpx


def alert_payload(*, fingerprint: str = "abc123", starts_at: str = "2026-07-21T10:00:00Z"):
    return {
        "receiver": "opspilot",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "service": "order-service",
                    "environment": "demo",
                    "severity": "P1",
                },
                "annotations": {"summary": "Order service error rate is high"},
                "startsAt": starts_at,
                "endsAt": None,
                "generatorURL": "http://prometheus/graph",
                "fingerprint": fingerprint,
            }
        ],
        "groupLabels": {"alertname": "HighErrorRate"},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager",
        "version": "4",
        "groupKey": "demo/order-service/HighErrorRate",
        "truncatedAlerts": 0,
    }


def resolved_alert_payload() -> dict:
    payload = alert_payload()
    payload["status"] = "resolved"
    payload["alerts"][0]["status"] = "resolved"
    payload["alerts"][0]["endsAt"] = "2026-07-21T10:10:00Z"
    return payload


async def test_repeated_alert_event_is_idempotent(client: httpx.AsyncClient) -> None:
    first = await client.post("/api/v1/webhooks/alertmanager", json=alert_payload())
    second = await client.post("/api/v1/webhooks/alertmanager", json=alert_payload())
    third = await client.post("/api/v1/webhooks/alertmanager", json=alert_payload())

    assert first.status_code == 202
    assert first.json()["created"] == 1
    assert second.json()["duplicate_events"] == 1
    assert third.json()["duplicate_events"] == 1
    assert first.json()["incident_ids"] == second.json()["incident_ids"]


async def test_distinct_alert_occurrences_merge_into_active_incident(
    client: httpx.AsyncClient,
) -> None:
    first = await client.post("/api/v1/webhooks/alertmanager", json=alert_payload())
    second = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(starts_at="2026-07-21T10:05:00Z"),
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["created"] == 0
    assert second.json()["merged"] == 1
    assert first.json()["incident_ids"] == second.json()["incident_ids"]


async def test_resolved_alert_closes_dedupe_window(client: httpx.AsyncClient) -> None:
    firing = await client.post("/api/v1/webhooks/alertmanager", json=alert_payload())
    resolved = await client.post("/api/v1/webhooks/alertmanager", json=resolved_alert_payload())
    recurrence = await client.post(
        "/api/v1/webhooks/alertmanager",
        json=alert_payload(starts_at="2026-07-21T11:00:00Z"),
    )

    assert firing.status_code == 202
    assert resolved.status_code == 202
    assert resolved.json()["merged"] == 1
    assert recurrence.status_code == 202
    assert recurrence.json()["created"] == 1
    assert recurrence.json()["incident_ids"] != firing.json()["incident_ids"]


async def test_concurrent_duplicate_alerts_create_one_incident(client: httpx.AsyncClient) -> None:
    responses = await asyncio.gather(
        *(client.post("/api/v1/webhooks/alertmanager", json=alert_payload()) for _ in range(20))
    )

    assert {response.status_code for response in responses} == {202}
    assert sum(response.json()["created"] for response in responses) == 1
    assert sum(response.json()["duplicate_events"] for response in responses) == 19
    assert len({response.json()["incident_ids"][0] for response in responses}) == 1


async def test_concurrent_occurrences_atomically_increment_alert_count(
    client: httpx.AsyncClient,
) -> None:
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/v1/webhooks/alertmanager",
                json=alert_payload(starts_at=f"2026-07-21T10:{minute:02d}:00Z"),
            )
            for minute in range(20)
        )
    )
    incident_id = responses[0].json()["incident_ids"][0]
    incident = await client.get(f"/api/v1/incidents/{incident_id}")

    assert {response.status_code for response in responses} == {202}
    assert incident.json()["alert_count"] == 20
