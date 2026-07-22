from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from opspilot.agent.models import Evidence
from opspilot.knowledge.models import RunbookSearchQuery
from opspilot.knowledge.retrieval import HybridRunbookRetriever
from opspilot.services.incidents import new_id, stable_digest


class SearchRunbooksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1000)
    service: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    environment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    top_k: int = Field(default=5, ge=1, le=20)


class SearchRunbooksTool:
    name = "search_runbooks"
    input_model = SearchRunbooksInput

    def __init__(self, retriever: HybridRunbookRetriever) -> None:
        self.retriever = retriever

    async def run(self, arguments: BaseModel) -> list[Evidence]:
        query = SearchRunbooksInput.model_validate(arguments)
        hits = await self.retriever.search(
            RunbookSearchQuery(
                text=query.query,
                service=query.service,
                environment=query.environment,
                top_k=query.top_k,
            )
        )
        return [
            Evidence(
                id=new_id("evd"),
                source_type="runbook",
                source_uri=f"{hit.source_uri}#chunk={hit.chunk_id}",
                content=hit.content,
                attributes={
                    "document_id": hit.document_id,
                    "chunk_id": hit.chunk_id,
                    "title": hit.title,
                    "heading": hit.heading,
                    "score": hit.score,
                    "keyword_score": hit.keyword_score,
                    "vector_score": hit.vector_score,
                    "checksum": stable_digest(hit.content),
                },
            )
            for hit in hits
        ]
