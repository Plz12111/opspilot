from sqlalchemy import func, select

from opspilot.db.models import RunbookChunkRecord, RunbookDocumentRecord

INVENTORY_RUNBOOK = """# Inventory Service Recovery

## Database connection pool exhausted

When `db_pool_in_use` reaches the configured maximum, inspect requests that do not release
connections. Compare the first error timestamp with the deployment history.

## Recovery

Rollback the latest inventory deployment if it introduced a connection leak. Restarting a
single demo instance can mitigate impact, but verify the pool returns below 70 percent.
"""


ORDER_RUNBOOK = """# Order Service High Error Rate

## Downstream timeout

Check whether inventory requests are returning 503 or exceeding the client timeout. Do not
retry non-idempotent order creation without the original order ID.

## Recovery

Confirm inventory health before restoring traffic and verify order error rate for five minutes.
"""


async def ingest(client, *, title: str, uri: str, service: str, content: str):
    return await client.post(
        "/api/v1/runbooks",
        json={
            "title": title,
            "source_uri": uri,
            "service": service,
            "environment": "demo",
            "content": content,
        },
    )


async def test_runbook_ingest_is_idempotent_and_updates_in_place(client) -> None:
    first = await ingest(
        client,
        title="Inventory recovery",
        uri="runbook://inventory/recovery",
        service="inventory-service",
        content=INVENTORY_RUNBOOK,
    )
    duplicate = await ingest(
        client,
        title="Inventory recovery",
        uri="runbook://inventory/recovery",
        service="inventory-service",
        content=INVENTORY_RUNBOOK,
    )
    updated = await ingest(
        client,
        title="Inventory recovery",
        uri="runbook://inventory/recovery",
        service="inventory-service",
        content=INVENTORY_RUNBOOK + "\n## Verification\nConfirm P95 latency is below 500 ms.\n",
    )

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert first.json()["chunk_count"] >= 2
    assert duplicate.json()["created"] is False
    assert duplicate.json()["updated"] is False
    assert duplicate.json()["document_id"] == first.json()["document_id"]
    assert updated.json()["updated"] is True
    assert updated.json()["document_id"] == first.json()["document_id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        documents = await session.scalar(select(func.count()).select_from(RunbookDocumentRecord))
        chunks = await session.scalar(select(func.count()).select_from(RunbookChunkRecord))
    assert documents == 1
    assert chunks == updated.json()["chunk_count"]


async def test_hybrid_search_ranks_service_specific_runbook_first(client) -> None:
    await ingest(
        client,
        title="Inventory recovery",
        uri="runbook://inventory/recovery",
        service="inventory-service",
        content=INVENTORY_RUNBOOK,
    )
    await ingest(
        client,
        title="Order recovery",
        uri="runbook://order/recovery",
        service="order-service",
        content=ORDER_RUNBOOK,
    )

    response = await client.get(
        "/api/v1/runbooks/search",
        params={
            "q": "database connection pool exhausted rollback deployment",
            "service": "inventory-service",
            "environment": "demo",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    hits = response.json()
    assert hits
    assert hits[0]["title"] == "Inventory recovery"
    assert hits[0]["service"] == "inventory-service"
    assert hits[0]["keyword_score"] > 0
    assert isinstance(hits[0]["vector_score"], float)


async def test_runbook_search_filters_unrelated_services(client) -> None:
    await ingest(
        client,
        title="Order recovery",
        uri="runbook://order/recovery",
        service="order-service",
        content=ORDER_RUNBOOK,
    )

    response = await client.get(
        "/api/v1/runbooks/search",
        params={"q": "timeout recovery", "service": "inventory-service"},
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_search_runbooks_tool_maps_external_query_field(client) -> None:
    from opspilot.agent.models import ToolRequest
    from opspilot.domain.enums import ToolExecutionStatus
    from opspilot.tools.gateway import ToolGateway
    from opspilot.tools.runbooks import SearchRunbooksTool

    await ingest(
        client,
        title="Inventory recovery",
        uri="runbook://inventory/tool-search",
        service="inventory-service",
        content=INVENTORY_RUNBOOK,
    )
    app = client._transport.app
    gateway = ToolGateway([SearchRunbooksTool(app.state.runbook_retriever)])

    result = await gateway.execute(
        ToolRequest(
            name="search_runbooks",
            arguments={
                "query": "connection pool rollback",
                "service": "inventory-service",
                "environment": "demo",
                "top_k": 2,
            },
        )
    )

    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.evidence
    assert result.evidence[0].source_type == "runbook"
