import time
from contextlib import AsyncExitStack

import httpx

from demo.services.gateway import create_app as create_gateway_app
from demo.services.inventory import create_app as create_inventory_app
from demo.services.order import create_app as create_order_app


async def asgi_client(stack: AsyncExitStack, app: object, base_url: str) -> httpx.AsyncClient:
    await stack.enter_async_context(app.router.lifespan_context(app))
    return await stack.enter_async_context(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)
    )


async def test_inventory_reservation_is_idempotent_and_metrics_are_exposed() -> None:
    app = create_inventory_app(fault_token="secret")
    async with AsyncExitStack() as stack:
        client = await asgi_client(stack, app, "http://inventory")
        payload = {"order_id": "order-1", "sku": "SKU-001", "quantity": 2}

        first = await client.post("/api/v1/inventory/reservations", json=payload)
        repeated = await client.post("/api/v1/inventory/reservations", json=payload)
        metrics = await client.get("/metrics")

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["remaining"] == 98
    assert metrics.status_code == 200
    assert "demo_http_requests_total" in metrics.text
    assert 'route="/api/v1/inventory/reservations"' in metrics.text


async def test_fault_configuration_requires_token_and_forces_failure() -> None:
    app = create_inventory_app(fault_token="secret")
    async with AsyncExitStack() as stack:
        client = await asgi_client(stack, app, "http://inventory")
        unauthorized = await client.put(
            "/internal/faults", json={"latency_ms": 0, "error_rate": 1.0}
        )
        configured = await client.put(
            "/internal/faults",
            headers={"X-Fault-Token": "secret"},
            json={"latency_ms": 0, "error_rate": 1.0},
        )
        failed = await client.post(
            "/api/v1/inventory/reservations",
            json={"order_id": "order-2", "sku": "SKU-001", "quantity": 1},
        )
        reset = await client.delete("/internal/faults", headers={"X-Fault-Token": "secret"})
        recovered = await client.post(
            "/api/v1/inventory/reservations",
            json={"order_id": "order-2", "sku": "SKU-001", "quantity": 1},
        )

    assert unauthorized.status_code == 401
    assert configured.status_code == 200
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "INJECTED_FAILURE"
    assert reset.status_code == 204
    assert recovered.status_code == 200


async def test_latency_fault_delays_inventory_request() -> None:
    app = create_inventory_app(fault_token="secret")
    async with AsyncExitStack() as stack:
        client = await asgi_client(stack, app, "http://inventory")
        await client.put(
            "/internal/faults",
            headers={"X-Fault-Token": "secret"},
            json={"latency_ms": 30, "error_rate": 0},
        )
        started = time.perf_counter()
        response = await client.post(
            "/api/v1/inventory/reservations",
            json={"order_id": "order-latency", "sku": "SKU-001", "quantity": 1},
        )
        elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed >= 0.025


async def test_gateway_order_inventory_chain_propagates_failure_and_recovers() -> None:
    inventory_app = create_inventory_app(fault_token="secret")
    async with AsyncExitStack() as stack:
        inventory_client = await asgi_client(stack, inventory_app, "http://inventory")
        order_app = create_order_app(inventory_client=inventory_client, fault_token="secret")
        order_client = await asgi_client(stack, order_app, "http://order")
        gateway_app = create_gateway_app(order_client=order_client, fault_token="secret")
        gateway_client = await asgi_client(stack, gateway_app, "http://gateway")

        success = await gateway_client.post(
            "/api/v1/orders",
            json={"order_id": "order-chain-1", "sku": "SKU-001", "quantity": 1},
        )
        await inventory_client.put(
            "/internal/faults",
            headers={"X-Fault-Token": "secret"},
            json={"latency_ms": 0, "error_rate": 1},
        )
        failed = await gateway_client.post(
            "/api/v1/orders",
            json={"order_id": "order-chain-2", "sku": "SKU-001", "quantity": 1},
        )
        await inventory_client.delete("/internal/faults", headers={"X-Fault-Token": "secret"})
        recovered = await gateway_client.post(
            "/api/v1/orders",
            json={"order_id": "order-chain-2", "sku": "SKU-001", "quantity": 1},
        )

    assert success.status_code == 200
    assert success.json()["status"] == "CONFIRMED"
    assert failed.status_code == 503
    assert recovered.status_code == 200
