from __future__ import annotations

from markdown_it import MarkdownIt

from opspilot.knowledge.models import ChunkDraft
from opspilot.knowledge.tokenization import tokenize


class MarkdownChunker:
    def __init__(self, max_chars: int = 1200, overlap_chars: int = 150) -> None:
        if max_chars < 200:
            raise ValueError("max_chars must be at least 200")
        if overlap_chars < 0 or overlap_chars >= max_chars // 2:
            raise ValueError("overlap_chars must be less than half of max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.parser = MarkdownIt()

    def chunk(self, content: str, default_heading: str) -> list[ChunkDraft]:
        tokens = self.parser.parse(content)
        sections: list[tuple[str, str]] = []
        heading = default_heading
        blocks: list[str] = []
        heading_inline_index = -1

        def flush() -> None:
            text = "\n".join(block for block in blocks if block.strip()).strip()
            if text:
                sections.append((heading, text))
            blocks.clear()

        for index, token in enumerate(tokens):
            if token.type == "heading_open":
                flush()
                if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
                    heading = tokens[index + 1].content.strip() or default_heading
                    heading_inline_index = index + 1
            elif token.type == "inline" and index != heading_inline_index:
                if token.content.strip():
                    blocks.append(token.content.strip())
            elif token.type in {"fence", "code_block"} and token.content.strip():
                blocks.append(token.content.strip())
        flush()

        if not sections and content.strip():
            sections.append((default_heading, content.strip()))

        drafts: list[ChunkDraft] = []
        for section_heading, text in sections:
            for piece in self._split(text):
                keywords = tokenize(f"{section_heading} {piece}")
                drafts.append(
                    ChunkDraft(
                        ordinal=len(drafts),
                        heading=section_heading[:500],
                        content=piece,
                        token_count=len(keywords),
                        keywords=keywords,
                    )
                )
        return drafts

    def _split(self, text: str) -> list[str]:
        pieces: list[str] = []
        remaining = text.strip()
        while len(remaining) > self.max_chars:
            cut = remaining.rfind(" ", 0, self.max_chars)
            if cut < self.max_chars // 2:
                cut = self.max_chars
            pieces.append(remaining[:cut].strip())
            next_start = max(cut - self.overlap_chars, 1)
            remaining = remaining[next_start:].strip()
        if remaining:
            pieces.append(remaining)
        return pieces
