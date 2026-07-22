from pydantic import BaseModel, ConfigDict

from opspilot.agent.models import Evidence
from opspilot.tools.gateway import ToolGateway


class AnyToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class StaticEvidenceTool:
    input_model = AnyToolInput

    def __init__(self, name: str, source_type: str) -> None:
        self.name = name
        self.source_type = source_type
        self.calls = 0

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        self.calls += 1
        return [
            Evidence(
                id=f"evd-{self.name}-{self.calls}",
                source_type=self.source_type,
                source_uri=f"test://{self.name}/{self.calls}",
                content=f"{self.name} evidence {self.calls}",
                attributes={"checksum": f"checksum-{self.name}-{self.calls}"},
            )
        ]


def fake_observation_gateway() -> ToolGateway:
    return ToolGateway(
        [
            StaticEvidenceTool("query_metrics", "metrics"),
            StaticEvidenceTool("query_logs", "logs"),
            StaticEvidenceTool("query_traces", "traces"),
            StaticEvidenceTool("search_runbooks", "runbook"),
        ]
    )
