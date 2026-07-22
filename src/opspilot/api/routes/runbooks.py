from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.api.dependencies import get_session
from opspilot.knowledge.models import (
    IngestResult,
    RunbookInput,
    RunbookSearchHit,
    RunbookSearchQuery,
)
from opspilot.knowledge.service import RunbookIngestService

router = APIRouter(prefix="/api/v1/runbooks", tags=["runbooks"])


@router.post("", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_runbook(
    payload: RunbookInput,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestResult:
    service = RunbookIngestService(session, request.app.state.embedding_provider)
    return await service.ingest(payload)


@router.get("/search", response_model=list[RunbookSearchHit])
async def search_runbooks(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=1000)],
    service: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_.-]+$")] = None,
    environment: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_.-]+$")] = None,
    top_k: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[RunbookSearchHit]:
    return await request.app.state.runbook_retriever.search(
        RunbookSearchQuery(
            text=q,
            service=service,
            environment=environment,
            top_k=top_k,
        )
    )
