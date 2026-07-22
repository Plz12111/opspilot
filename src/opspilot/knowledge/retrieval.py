from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot.db.models import RunbookChunkRecord, RunbookDocumentRecord
from opspilot.knowledge.models import (
    EmbeddingProvider,
    RunbookSearchHit,
    RunbookSearchQuery,
)
from opspilot.knowledge.tokenization import tokenize


class HybridRunbookRetriever:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_provider: EmbeddingProvider,
        candidate_limit: int = 2000,
        rrf_k: int = 60,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider
        self.candidate_limit = candidate_limit
        self.rrf_k = rrf_k

    async def search(self, query: RunbookSearchQuery) -> list[RunbookSearchHit]:
        async with self.session_factory() as session:
            statement = (
                select(RunbookChunkRecord, RunbookDocumentRecord)
                .join(
                    RunbookDocumentRecord,
                    RunbookDocumentRecord.id == RunbookChunkRecord.document_id,
                )
                .limit(self.candidate_limit)
            )
            if query.service:
                statement = statement.where(
                    or_(
                        RunbookDocumentRecord.service == query.service,
                        RunbookDocumentRecord.service.is_(None),
                    )
                )
            if query.environment:
                statement = statement.where(
                    or_(
                        RunbookDocumentRecord.environment == query.environment,
                        RunbookDocumentRecord.environment.is_(None),
                    )
                )
            rows = list((await session.execute(statement)).all())
        if not rows:
            return []

        query_tokens = tokenize(query.text)
        query_embedding = (await self.embedding_provider.embed([query.text]))[0]
        keyword_scores = self._keyword_scores(query_tokens, [row[0] for row in rows])
        vector_scores = [self._cosine(query_embedding, row[0].embedding) for row in rows]
        keyword_ranks = self._ranks(keyword_scores)
        vector_ranks = self._ranks(vector_scores)

        hits: list[RunbookSearchHit] = []
        query_token_set = set(query_tokens)
        for index, (chunk, document) in enumerate(rows):
            rrf = 1 / (self.rrf_k + keyword_ranks[index]) + 1 / (self.rrf_k + vector_ranks[index])
            heading_tokens = set(tokenize(f"{document.title} {chunk.heading}"))
            heading_coverage = (
                len(query_token_set & heading_tokens) / len(query_token_set)
                if query_token_set
                else 0
            )
            metadata_bonus = 0.0
            if query.service and document.service == query.service:
                metadata_bonus += 0.02
            if query.environment and document.environment == query.environment:
                metadata_bonus += 0.01
            score = rrf + heading_coverage * 0.03 + metadata_bonus
            hits.append(
                RunbookSearchHit(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    title=document.title,
                    source_uri=document.source_uri,
                    heading=chunk.heading,
                    content=chunk.content,
                    service=document.service,
                    environment=document.environment,
                    score=score,
                    keyword_score=keyword_scores[index],
                    vector_score=vector_scores[index],
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: query.top_k]

    @staticmethod
    def _keyword_scores(query_tokens: list[str], chunks: list[RunbookChunkRecord]) -> list[float]:
        if not query_tokens:
            return [0.0] * len(chunks)
        document_frequency = {
            token: sum(token in set(chunk.keywords) for chunk in chunks)
            for token in set(query_tokens)
        }
        average_length = sum(max(chunk.token_count, 1) for chunk in chunks) / len(chunks)
        scores: list[float] = []
        for chunk in chunks:
            frequencies = Counter(chunk.keywords)
            score = 0.0
            for token in query_tokens:
                frequency = frequencies[token]
                if not frequency:
                    continue
                inverse_frequency = math.log(
                    1
                    + (len(chunks) - document_frequency[token] + 0.5)
                    / (document_frequency[token] + 0.5)
                )
                denominator = frequency + 1.5 * (
                    0.25 + 0.75 * max(chunk.token_count, 1) / average_length
                )
                score += inverse_frequency * (frequency * 2.5) / denominator
            scores.append(score)
        return scores

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True))

    @staticmethod
    def _ranks(scores: list[float]) -> list[int]:
        order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        ranks = [0] * len(scores)
        for rank, index in enumerate(order, start=1):
            ranks[index] = rank
        return ranks
