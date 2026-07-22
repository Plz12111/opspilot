from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class RunbookInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source_uri: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=20, max_length=1_000_000)
    service: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    environment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")


class ChunkDraft(BaseModel):
    ordinal: int
    heading: str
    content: str
    token_count: int
    keywords: list[str]


class IngestResult(BaseModel):
    document_id: str
    created: bool
    updated: bool
    chunk_count: int
    checksum: str


class RunbookSearchQuery(BaseModel):
    text: str = Field(min_length=2, max_length=1000)
    service: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    environment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    top_k: int = Field(default=5, ge=1, le=20)


class RunbookSearchHit(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source_uri: str
    heading: str
    content: str
    service: str | None
    environment: str | None
    score: float
    keyword_score: float
    vector_score: float


class EmbeddingProvider(Protocol):
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
