from __future__ import annotations

from pydantic import BaseModel, Field

from opspilot.knowledge.models import RunbookSearchQuery
from opspilot.knowledge.retrieval import HybridRunbookRetriever


class RetrievalCase(BaseModel):
    id: str
    query: str
    expected_source_uri: str
    service: str | None = None
    environment: str | None = None


class RetrievalMetrics(BaseModel):
    case_count: int
    recall_at_k: float = Field(ge=0, le=1)
    mean_reciprocal_rank: float = Field(ge=0, le=1)


class RunbookRetrievalEvaluator:
    def __init__(self, retriever: HybridRunbookRetriever) -> None:
        self.retriever = retriever

    async def evaluate(self, cases: list[RetrievalCase], top_k: int = 3) -> RetrievalMetrics:
        if not cases:
            raise ValueError("at least one retrieval case is required")
        recalled = 0
        reciprocal_rank_sum = 0.0
        for case in cases:
            hits = await self.retriever.search(
                RunbookSearchQuery(
                    text=case.query,
                    service=case.service,
                    environment=case.environment,
                    top_k=top_k,
                )
            )
            rank = next(
                (
                    index
                    for index, hit in enumerate(hits, start=1)
                    if hit.source_uri == case.expected_source_uri
                ),
                None,
            )
            if rank is not None:
                recalled += 1
                reciprocal_rank_sum += 1 / rank
        return RetrievalMetrics(
            case_count=len(cases),
            recall_at_k=recalled / len(cases),
            mean_reciprocal_rank=reciprocal_rank_sum / len(cases),
        )
