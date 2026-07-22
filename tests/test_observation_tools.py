import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, ConfigDict

from opspilot.agent.models import Evidence, ToolRequest
from opspilot.domain.enums import ToolExecutionStatus
from opspilot.tools.gateway import ToolGateway
from opspilot.tools.observability.jaeger import QueryTracesTool
from opspilot.tools.observability.loki import QueryLogsTool
from opspilot.tools.observability.prometheus import QueryMetricsTool


def time_window() -> tuple[str, str]:
    end = datetime.now(UTC)
    return (end - timedelta(minutes=10)).isoformat(), end.isoformat()


async def test_observation_tools_normalize_provider_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/query_range":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "matrix",
                        "result": [{"metric": {"service": "order-service"}, "values": [[1, "2"]]}],
                    },
                },
            )
        if request.url.path == "/loki/api/v1/query_range":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "streams",
                        "result": [
                            {
                                "stream": {"service_name": "order-service"},
                                "values": [["1", "ERROR inventory timeout"]],
                            }
                        ],
                    },
                },
            )
        if request.url.path == "/api/traces":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "traceID": "trace-1",
                            "spans": [{"operationName": "inventory.reserve", "duration": 800000}],
                            "processes": {},
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://observability"
    ) as client:
        gateway = ToolGateway(
            [QueryMetricsTool(client), QueryLogsTool(client), QueryTracesTool(client)]
        )
        start, end = time_window()
        metrics = await gateway.execute(
            ToolRequest(
                name="query_metrics",
                arguments={"query": "up", "start": start, "end": end},
            )
        )
        logs = await gateway.execute(
            ToolRequest(
                name="query_logs",
                arguments={"query": '{service="order"}', "start": start, "end": end},
            )
        )
        traces = await gateway.execute(
            ToolRequest(
                name="query_traces",
                arguments={"service": "order-service", "start": start, "end": end},
            )
        )

    assert metrics.status == ToolExecutionStatus.SUCCESS
    assert metrics.evidence[0].source_type == "metrics"
    assert logs.status == ToolExecutionStatus.SUCCESS
    assert "inventory timeout" in logs.evidence[0].content
    assert traces.status == ToolExecutionStatus.SUCCESS
    assert "trace-1" in traces.evidence[0].content


class AnyInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class SlowTool:
    name = "slow_tool"
    input_model = AnyInput

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        await asyncio.sleep(0.05)
        return []


class LargeTool:
    name = "large_tool"
    input_model = AnyInput

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        return [
            Evidence(
                id="evd-large",
                source_type="test",
                source_uri="test://large",
                content="x" * 100,
            )
        ]


async def test_gateway_enforces_timeout_validation_and_truncation() -> None:
    gateway = ToolGateway(
        [SlowTool(), LargeTool()],
        timeout_seconds=0.01,
        max_evidence_chars=10,
    )
    timed_out = await gateway.execute(ToolRequest(name="slow_tool", arguments={}))
    truncated = await gateway.execute(ToolRequest(name="large_tool", arguments={}))
    unknown = await gateway.execute(ToolRequest(name="unknown_tool", arguments={}))

    assert timed_out.status == ToolExecutionStatus.TIMEOUT
    assert truncated.status == ToolExecutionStatus.SUCCESS
    assert truncated.evidence[0].content == "x" * 10
    assert truncated.evidence[0].attributes["truncated"] is True
    assert unknown.status == ToolExecutionStatus.ERROR


async def test_observation_query_rejects_oversized_time_range() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        base_url="http://prometheus",
    ) as client:
        gateway = ToolGateway([QueryMetricsTool(client)])
        end = datetime.now(UTC)
        result = await gateway.execute(
            ToolRequest(
                name="query_metrics",
                arguments={
                    "query": "up",
                    "start": (end - timedelta(hours=7)).isoformat(),
                    "end": end.isoformat(),
                },
            )
        )

    assert result.status == ToolExecutionStatus.ERROR
    assert result.error is not None
    assert "cannot exceed 6 hours" in result.error
