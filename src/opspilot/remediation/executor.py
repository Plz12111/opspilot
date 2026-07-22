from __future__ import annotations

import asyncio
from typing import Any, Protocol


class ActionExecutor(Protocol):
    async def execute(
        self,
        action_type: str,
        target_environment: str,
        service: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]: ...


class DemoActionExecutor:
    def __init__(self) -> None:
        self.executions: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def execute(
        self,
        action_type: str,
        target_environment: str,
        service: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        if target_environment not in {"demo", "staging"}:
            raise ValueError("demo executor refuses non-demo/staging environments")
        if action_type not in {"restart_service", "rollback_deployment"}:
            raise ValueError("demo executor received a non-allowlisted action")
        async with self._lock:
            execution_number = len(self.executions) + 1
            result = {
                "simulated": True,
                "execution_number": execution_number,
                "action_type": action_type,
                "environment": target_environment,
                "service": service,
                "parameters": parameters,
            }
            self.executions.append(result)
            return result
