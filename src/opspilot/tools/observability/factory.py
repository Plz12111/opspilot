from __future__ import annotations

from dataclasses import dataclass

import httpx

from opspilot.config import Settings
from opspilot.tools.gateway import ToolGateway
from opspilot.tools.observability.jaeger import QueryTracesTool
from opspilot.tools.observability.loki import QueryLogsTool
from opspilot.tools.observability.prometheus import QueryMetricsTool


@dataclass(slots=True)
class ObservationToolset:
    gateway: ToolGateway
    clients: list[httpx.AsyncClient]

    async def close(self) -> None:
        for client in self.clients:
            await client.aclose()


def create_observation_toolset(settings: Settings) -> ObservationToolset:
    timeout = httpx.Timeout(settings.tool_timeout_seconds)
    prometheus = httpx.AsyncClient(base_url=settings.prometheus_url, timeout=timeout)
    loki = httpx.AsyncClient(base_url=settings.loki_url, timeout=timeout)
    jaeger = httpx.AsyncClient(base_url=settings.jaeger_url, timeout=timeout)
    gateway = ToolGateway(
        [QueryMetricsTool(prometheus), QueryLogsTool(loki), QueryTracesTool(jaeger)],
        timeout_seconds=settings.tool_timeout_seconds,
        max_evidence_chars=settings.tool_max_evidence_chars,
    )
    return ObservationToolset(gateway, [prometheus, loki, jaeger])
