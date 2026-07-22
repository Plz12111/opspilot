from datetime import UTC, datetime, timedelta

from opspilot.agent.graph import InvestigationRunner
from opspilot.agent.models import InvestigationContext
from opspilot.domain.enums import InvestigationStatus
from tests.fake_tools import fake_observation_gateway


def context(step_budget: int) -> InvestigationContext:
    end = datetime.now(UTC)
    return InvestigationContext(
        run_id="run-test",
        incident_id="inc-test",
        service="inventory-service",
        environment="demo",
        start_time=end - timedelta(minutes=15),
        end_time=end,
        step_budget=step_budget,
    )


async def test_graph_executes_complete_read_only_plan() -> None:
    result = await InvestigationRunner(fake_observation_gateway()).run(context(step_budget=6))

    assert result.status == InvestigationStatus.COMPLETED
    assert [item.name for item in result.plan] == [
        "query_metrics",
        "query_metrics",
        "query_logs",
        "query_traces",
        "search_runbooks",
    ]
    assert result.steps_used == 5
    assert len(result.evidence) == 5
    assert result.diagnosis.evidence_ids == [item.id for item in result.evidence]


async def test_graph_stops_at_step_budget() -> None:
    result = await InvestigationRunner(fake_observation_gateway()).run(context(step_budget=2))

    assert result.status == InvestigationStatus.BUDGET_EXHAUSTED
    assert result.steps_used == 2
    assert len(result.executions) == 2
