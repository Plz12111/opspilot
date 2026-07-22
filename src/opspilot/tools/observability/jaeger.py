from typing import Any

import httpx
from pydantic import BaseModel, Field

from opspilot.agent.models import Evidence
from opspilot.tools.observability.common import TimeRangeInput, make_evidence


class QueryTracesInput(TimeRangeInput):
    service: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    limit: int = Field(default=20, ge=1, le=100)


class QueryTracesTool:
    name = "query_traces"
    input_model = QueryTracesInput

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        query = QueryTracesInput.model_validate(arguments)
        response = await self.client.get(
            "/api/traces",
            params={
                "service": query.service,
                "start": int(query.start.timestamp() * 1_000_000),
                "end": int(query.end.timestamp() * 1_000_000),
                "limit": query.limit,
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        traces = payload.get("data", [])[: query.limit]
        summaries = [
            {
                "traceID": trace.get("traceID"),
                "spans": trace.get("spans", []),
                "processes": trace.get("processes", {}),
            }
            for trace in traces
        ]
        return [
            make_evidence(
                "traces",
                "jaeger://traces",
                {"traces": summaries},
                {"service": query.service, "trace_count": len(summaries)},
            )
        ]
