import subprocess

from sqlalchemy import func, select

from opspilot.db.models import (
    ActionExecutionRecord,
    IncidentRecord,
    InvestigationRunRecord,
    ProposedActionRecord,
    RunbookDocumentRecord,
)
from opspilot.demo.cli import seed_workflow
from tests.fake_tools import fake_observation_gateway


async def test_demo_workflow_is_complete_and_idempotent(client) -> None:
    app = client._transport.app
    app.state.tool_gateway = fake_observation_gateway()

    first = await seed_workflow(client, "http://test")
    second = await seed_workflow(client, "http://test")

    assert first == second
    assert first["run_status"] == "COMPLETED"
    assert first["approval"] == "APPROVED"
    assert first["execution"] == "SUCCESS"
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(IncidentRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(InvestigationRunRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(ProposedActionRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(ActionExecutionRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(RunbookDocumentRecord)) == 2


def test_installed_demo_command_can_load() -> None:
    result = subprocess.run(
        ["opspilot-demo", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Create a complete OpsPilot demo workflow" in result.stdout
