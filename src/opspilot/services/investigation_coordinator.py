from __future__ import annotations

import asyncio
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot.agent.graph import InvestigationRunner
from opspilot.db.models import InvestigationJobRecord
from opspilot.domain.enums import InvestigationStatus
from opspilot.services.investigations import InvestigationService


class InvestigationCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner_factory: Callable[[], InvestigationRunner],
    ) -> None:
        self.session_factory = session_factory
        self.runner_factory = runner_factory
        self.tasks: dict[str, asyncio.Task[None]] = {}

    async def recover(self) -> int:
        async with self.session_factory() as session:
            run_ids = list(
                (
                    await session.scalars(
                        select(InvestigationJobRecord.run_id).where(
                            InvestigationJobRecord.status.in_(
                                [InvestigationStatus.PENDING, InvestigationStatus.RUNNING]
                            )
                        )
                    )
                ).all()
            )
        for run_id in run_ids:
            self.schedule(run_id)
        return len(run_ids)

    def schedule(self, run_id: str) -> asyncio.Task[None]:
        existing = self.tasks.get(run_id)
        if existing is not None and not existing.done():
            return existing
        task = asyncio.create_task(self._execute(run_id), name=f"investigation:{run_id}")
        self.tasks[run_id] = task
        task.add_done_callback(lambda completed: self._discard(run_id, completed))
        return task

    async def wait(self, run_id: str) -> None:
        task = self.tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def close(self) -> None:
        pending = [task for task in self.tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()

    async def _execute(self, run_id: str) -> None:
        try:
            async with self.session_factory() as session:
                service = InvestigationService(session, self.runner_factory())
                await service.execute(run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # InvestigationService persists the failure and emits a terminal event.
            return

    def _discard(self, run_id: str, task: asyncio.Task[None]) -> None:
        if self.tasks.get(run_id) is task:
            self.tasks.pop(run_id, None)
