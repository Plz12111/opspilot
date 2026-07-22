import httpx

from opspilot.api.routes import health


async def test_health_endpoints(client: httpx.AsyncClient) -> None:
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "checks": {"database": {"status": "up", "critical": True}},
    }


async def test_ready_reports_optional_dependencies_as_degraded(client, monkeypatch) -> None:
    app = client._transport.app
    app.state.settings.readiness_check_external = True

    async def unavailable(*_args) -> bool:
        return False

    monkeypatch.setattr(health, "_check_redis", unavailable)
    monkeypatch.setattr(health, "_check_http", unavailable)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["database"] == {"status": "up", "critical": True}
    assert response.json()["checks"]["prometheus"] == {
        "status": "down",
        "critical": False,
    }
