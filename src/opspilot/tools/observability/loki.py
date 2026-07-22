from typing import Any

import httpx
from pydantic import BaseModel, Field

from opspilot.agent.models import Evidence
from opspilot.tools.observability.common import TimeRangeInput, make_evidence


class QueryLogsInput(TimeRangeInput):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=100, ge=1, le=500)


class QueryLogsTool:
    name = "query_logs"
    input_model = QueryLogsInput

    def __init__(self, client: httpx.AsyncClient, max_streams: int = 20) -> None:
        self.client = client
        self.max_streams = max_streams

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        query = QueryLogsInput.model_validate(arguments)
        response = await self.client.get(
            "/loki/api/v1/query_range",
            params={
                "query": query.query,
                "start": int(query.start.timestamp() * 1_000_000_000),
                "end": int(query.end.timestamp() * 1_000_000_000),
                "limit": query.limit,
                "direction": "backward",
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if payload.get("status") != "success":
            raise ValueError("Loki query did not return success")
        streams = payload.get("data", {}).get("result", [])[: self.max_streams]
        return [
            make_evidence(
                "logs",
                "loki://query_range",
                {"resultType": payload.get("data", {}).get("resultType"), "result": streams},
                {"query": query.query, "stream_count": len(streams)},
            )
        ]
