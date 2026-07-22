from typing import Any

import httpx
from pydantic import BaseModel, Field

from opspilot.agent.models import Evidence
from opspilot.tools.observability.common import TimeRangeInput, make_evidence


class QueryMetricsInput(TimeRangeInput):
    query: str = Field(min_length=1, max_length=2000)
    step_seconds: int = Field(default=30, ge=1, le=3600)


class QueryMetricsTool:
    name = "query_metrics"
    input_model = QueryMetricsInput

    def __init__(self, client: httpx.AsyncClient, max_series: int = 20) -> None:
        self.client = client
        self.max_series = max_series

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        query = QueryMetricsInput.model_validate(arguments)
        response = await self.client.get(
            "/api/v1/query_range",
            params={
                "query": query.query,
                "start": query.start.timestamp(),
                "end": query.end.timestamp(),
                "step": query.step_seconds,
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if payload.get("status") != "success":
            raise ValueError(f"Prometheus query failed: {payload.get('error', 'unknown error')}")
        result = payload.get("data", {}).get("result", [])[: self.max_series]
        return [
            make_evidence(
                "metrics",
                "prometheus://query_range",
                {"resultType": payload.get("data", {}).get("resultType"), "result": result},
                {"query": query.query, "series_count": len(result)},
            )
        ]
