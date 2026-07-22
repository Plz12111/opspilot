from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ValidationError

from opspilot.agent.models import Evidence, ToolExecution, ToolRequest
from opspilot.domain.enums import ToolExecutionStatus
from opspilot.services.incidents import new_id


class ReadOnlyTool(Protocol):
    name: str
    input_model: type[BaseModel]

    async def run(self, arguments: BaseModel) -> list[Evidence]: ...


class ToolGateway:
    def __init__(
        self,
        tools: list[ReadOnlyTool] | None = None,
        timeout_seconds: float = 8.0,
        max_evidence_chars: int = 20_000,
    ) -> None:
        self._tools = {tool.name: tool for tool in tools or []}
        self.timeout_seconds = timeout_seconds
        self.max_evidence_chars = max_evidence_chars

    def register(self, tool: ReadOnlyTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is already registered")
        self._tools[tool.name] = tool

    async def execute(self, request: ToolRequest) -> ToolExecution:
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        tool = self._tools.get(request.name)
        if tool is None:
            return self._failure(
                request,
                started_at,
                started,
                ToolExecutionStatus.ERROR,
                "tool is not registered",
            )
        try:
            arguments = tool.input_model.model_validate(request.arguments)
            async with asyncio.timeout(self.timeout_seconds):
                evidence = await tool.run(arguments)
            evidence = [self._truncate(item) for item in evidence]
            return ToolExecution(
                id=new_id("call"),
                request=request,
                status=ToolExecutionStatus.SUCCESS,
                started_at=started_at,
                latency_ms=int((time.perf_counter() - started) * 1000),
                evidence=evidence,
            )
        except TimeoutError:
            return self._failure(
                request,
                started_at,
                started,
                ToolExecutionStatus.TIMEOUT,
                f"tool exceeded {self.timeout_seconds:g}s timeout",
            )
        except ValidationError as exc:
            return self._failure(
                request,
                started_at,
                started,
                ToolExecutionStatus.ERROR,
                f"invalid tool arguments: {exc.errors(include_url=False)}",
            )
        except Exception as exc:
            return self._failure(
                request,
                started_at,
                started,
                ToolExecutionStatus.ERROR,
                f"{type(exc).__name__}: {str(exc)[:400]}",
            )

    def _truncate(self, evidence: Evidence) -> Evidence:
        if len(evidence.content) <= self.max_evidence_chars:
            return evidence
        return evidence.model_copy(
            update={
                "content": evidence.content[: self.max_evidence_chars],
                "attributes": {**evidence.attributes, "truncated": True},
            }
        )

    @staticmethod
    def _failure(
        request: ToolRequest,
        started_at: datetime,
        started: float,
        status: ToolExecutionStatus,
        error: str,
    ) -> ToolExecution:
        return ToolExecution(
            id=new_id("call"),
            request=request,
            status=status,
            started_at=started_at,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error,
        )
