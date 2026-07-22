from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from opspilot.agent.models import Evidence
from opspilot.evaluation.models import EvaluationCase, RecordedObservation
from opspilot.tools.gateway import ToolGateway


class ReplayInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class RecordedEvidenceTool:
    input_model = ReplayInput

    def __init__(
        self,
        name: str,
        observations: list[RecordedObservation],
        fail: bool = False,
    ) -> None:
        self.name = name
        self.observations = observations
        self.fail = fail
        self.calls = 0

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"recorded {self.name} outage")
        return [
            Evidence(
                id=item.id,
                source_type=item.source_type,
                source_uri=f"recording://{self.name}/{item.id}",
                content=item.content,
                attributes={"evaluation_recording": True},
            )
            for item in self.observations
            if item.call_index == self.calls
        ]


def replay_gateway(case: EvaluationCase) -> ToolGateway:
    tool_names = ["query_metrics", "query_logs", "query_traces", "search_runbooks"]
    tools = [
        RecordedEvidenceTool(
            name,
            [item for item in case.observations if item.tool_name == name],
            fail=name in case.failed_tools,
        )
        for name in tool_names
    ]
    return ToolGateway(tools, timeout_seconds=1.0)
