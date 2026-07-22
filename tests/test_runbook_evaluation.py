import json

from anyio import Path

from opspilot.knowledge.evaluation import RetrievalCase, RunbookRetrievalEvaluator
from tests.test_runbooks import INVENTORY_RUNBOOK, ORDER_RUNBOOK, ingest


async def test_runbook_retrieval_baseline_reaches_full_recall(client) -> None:
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
    raw_cases = json.loads(await Path("evals/runbooks/cases.json").read_text())
    cases = [RetrievalCase.model_validate(item) for item in raw_cases]
    app = client._transport.app

    metrics = await RunbookRetrievalEvaluator(app.state.runbook_retriever).evaluate(cases, top_k=3)

    assert metrics.case_count == 4
    assert metrics.recall_at_k == 1.0
    assert metrics.mean_reciprocal_rank == 1.0
