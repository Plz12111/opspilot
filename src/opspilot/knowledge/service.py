from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.db.models import RunbookChunkRecord, RunbookDocumentRecord
from opspilot.knowledge.chunking import MarkdownChunker
from opspilot.knowledge.models import EmbeddingProvider, IngestResult, RunbookInput
from opspilot.services.incidents import new_id, stable_digest


class RunbookIngestService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        chunker: MarkdownChunker | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.chunker = chunker or MarkdownChunker()

    async def ingest(self, runbook: RunbookInput) -> IngestResult:
        checksum = stable_digest(runbook.content)
        document = await self.session.scalar(
            select(RunbookDocumentRecord).where(
                RunbookDocumentRecord.source_uri == runbook.source_uri
            )
        )
        if document is not None and document.checksum == checksum:
            chunk_count = await self.session.scalar(
                select(func.count())
                .select_from(RunbookChunkRecord)
                .where(RunbookChunkRecord.document_id == document.id)
            )
            return IngestResult(
                document_id=document.id,
                created=False,
                updated=False,
                chunk_count=chunk_count or 0,
                checksum=checksum,
            )

        created = document is None
        if document is None:
            document = RunbookDocumentRecord(
                id=new_id("doc"),
                title=runbook.title,
                source_uri=runbook.source_uri,
                service=runbook.service,
                environment=runbook.environment,
                content=runbook.content,
                checksum=checksum,
            )
            self.session.add(document)
            await self.session.flush()
        else:
            await self.session.execute(
                delete(RunbookChunkRecord).where(RunbookChunkRecord.document_id == document.id)
            )
            document.title = runbook.title
            document.service = runbook.service
            document.environment = runbook.environment
            document.content = runbook.content
            document.checksum = checksum

        drafts = self.chunker.chunk(runbook.content, runbook.title)
        embeddings = await self.embedding_provider.embed(
            [f"{draft.heading}\n{draft.content}" for draft in drafts]
        )
        for draft, embedding in zip(drafts, embeddings, strict=True):
            self.session.add(
                RunbookChunkRecord(
                    id=new_id("chk"),
                    document_id=document.id,
                    ordinal=draft.ordinal,
                    heading=draft.heading,
                    content=draft.content,
                    token_count=draft.token_count,
                    keywords=draft.keywords,
                    embedding=embedding,
                    checksum=stable_digest(draft.content),
                )
            )
        await self.session.commit()
        return IngestResult(
            document_id=document.id,
            created=created,
            updated=not created,
            chunk_count=len(drafts),
            checksum=checksum,
        )
