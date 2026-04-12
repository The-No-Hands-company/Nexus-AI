"""
VersaAI Document Chunker — production-grade text splitting.

Splits documents into overlapping chunks that respect structural boundaries:
- Markdown headers (split before ## sections)
- Code blocks (never split inside ```)
- Paragraph boundaries (prefer splitting at double newlines)
- Sentence boundaries (prefer splitting at sentence-end punctuation)

Designed for RAG ingestion: small enough for embedding models, large enough
for semantic coherence.

Usage:
    >>> from versaai.rag.chunker import DocumentChunker, ChunkerConfig
    >>> chunker = DocumentChunker()
    >>> chunks = chunker.split("long document text...")
    >>> for c in chunks:
    ...     print(c.index, len(c.text), c.metadata)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Hierarchy of separators — tried in order from most structural to least.
_DEFAULT_SEPARATORS: List[str] = [
    "\n## ",       # Markdown H2 header
    "\n### ",      # Markdown H3 header
    "\n#### ",     # Markdown H4 header
    "\n\n",        # Paragraph boundary
    "\n",          # Line break
    ". ",          # Sentence end
    "? ",          # Question end
    "! ",          # Exclamation end
    "; ",          # Semicolon
    ", ",          # Comma phrase
    " ",           # Word boundary
]


@dataclass
class ChunkerConfig:
    """Configuration for the document chunker."""

    chunk_size: int = 512      # default chunk size
    chunk_overlap: int = 64     # default overlap
    separators: List[str] = field(default_factory=lambda: list(_DEFAULT_SEPARATORS))
    strip_whitespace: bool = True
    keep_separator: bool = True
    min_chunk_size: int = 50  # Discard trivially small chunks

    def __post_init__(self):
        if self.chunk_overlap >= self.chunk_size:
            self.chunk_overlap = self.chunk_size // 4


@dataclass
class Chunk:
    """A single text chunk with positional metadata."""

    text: str
    index: int                           # ordinal position in document
    start_char: int                      # character offset in original document
    end_char: int                        # character offset (exclusive)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)


class DocumentChunker:
    """
    Recursive character text splitter with structural awareness.

    Algorithm:
    1. Try the most structural separator first (e.g., markdown headers).
    2. Split text at that separator into segments.
    3. Merge consecutive small segments until they approach chunk_size.
    4. If any merged segment still exceeds chunk_size, recurse with the
       next separator in the hierarchy.
    5. Apply overlap by prepending the tail of the previous chunk.
    """

    def __init__(self, config: Optional[ChunkerConfig] = None):
        self.config = config or ChunkerConfig()

    def split(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """
        Split a document into overlapping chunks.

        Args:
            text: The full document text.
            metadata: Optional metadata dict attached to each chunk.

        Returns:
            List of Chunk objects with positional info.
        """
        if not text or not text.strip():
            return []

        # Pre-process: protect code blocks from being split
        text_clean, code_map = self._protect_code_blocks(text)

        # Recursive split
        raw_chunks = self._split_recursive(text_clean, self.config.separators)

        # Restore code blocks
        raw_chunks = [self._restore_code_blocks(c, code_map) for c in raw_chunks]

        # Apply overlap
        overlapped = self._apply_overlap(raw_chunks)

        # Build Chunk objects with positional metadata
        chunks: List[Chunk] = []
        char_offset = 0
        base_meta = metadata or {}
        for i, chunk_text in enumerate(overlapped):
            if self.config.strip_whitespace:
                chunk_text = chunk_text.strip()
            if len(chunk_text) < self.config.min_chunk_size:
                continue

            # Find approximate position in original text
            pos = text.find(chunk_text[:80], max(0, char_offset - 100))
            if pos < 0:
                pos = char_offset

            chunk_meta = {
                **base_meta,
                "chunk_index": i,
                "chunk_size": len(chunk_text),
            }
            chunks.append(Chunk(
                text=chunk_text,
                index=len(chunks),
                start_char=pos,
                end_char=pos + len(chunk_text),
                metadata=chunk_meta,
            ))
            char_offset = pos + len(chunk_text)

        logger.debug(
            "Chunked %d chars → %d chunks (avg %d chars)",
            len(text),
            len(chunks),
            sum(c.char_count for c in chunks) // max(len(chunks), 1),
        )
        return chunks

    def split_documents(
        self,
        documents: List[Dict[str, Any]],
        text_key: str = "text",
    ) -> List[Dict[str, Any]]:
        """
        Split a list of document dicts into chunks.

        Each input document is split; metadata from the original document
        is propagated to each resulting chunk dict.

        Returns:
            List of dicts with keys: text, source_doc_index, chunk_index, ...
        """
        all_chunks: List[Dict[str, Any]] = []
        for doc_idx, doc in enumerate(documents):
            text = doc.get(text_key, "")
            meta = {k: v for k, v in doc.items() if k != text_key}
            meta["source_doc_index"] = doc_idx

            chunks = self.split(text, metadata=meta)
            for chunk in chunks:
                all_chunks.append({
                    "text": chunk.text,
                    **chunk.metadata,
                })
        return all_chunks

    # ----- internal: recursive split --------------------------------------

    def _split_recursive(self, text: str, separators: List[str]) -> List[str]:
        """Recursively split text using the separator hierarchy."""
        chunk_size = self.config.chunk_size

        # Base case: text fits in one chunk
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        # Find the best separator that actually appears in this text
        separator = ""
        remaining_seps = separators
        for i, sep in enumerate(separators):
            if sep in text:
                separator = sep
                remaining_seps = separators[i + 1:]
                break

        # If no separator found, hard-split at chunk_size
        if not separator:
            return self._hard_split(text, chunk_size)

        # Split and merge
        parts = text.split(separator)
        merged: List[str] = []
        current = ""

        for part in parts:
            candidate = (
                current + separator + part if current else part
            ) if self.config.keep_separator and current else (
                part if not current else current + separator + part
            )

            if len(candidate) <= chunk_size:
                current = candidate
            else:
                # Flush current buffer
                if current:
                    merged.append(current)
                # If this single part exceeds chunk_size, recurse
                if len(part) > chunk_size and remaining_seps:
                    sub = self._split_recursive(part, remaining_seps)
                    merged.extend(sub)
                    current = ""
                else:
                    current = part

        if current:
            merged.append(current)

        return merged

    def _hard_split(self, text: str, size: int) -> List[str]:
        """Last-resort character-level split."""
        return [text[i : i + size] for i in range(0, len(text), size)]

    # ----- internal: overlap ----------------------------------------------

    def _apply_overlap(self, chunks: List[str]) -> List[str]:
        """Prepend the tail of the previous chunk as overlap context."""
        overlap = self.config.chunk_overlap
        if overlap <= 0 or len(chunks) <= 1:
            return chunks

        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            result.append(prev_tail + chunks[i])
        return result

    # ----- internal: code block protection --------------------------------

    _CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

    def _protect_code_blocks(self, text: str) -> tuple[str, Dict[str, str]]:
        """Replace code blocks with placeholders to prevent splitting inside them."""
        code_map: Dict[str, str] = {}
        counter = [0]

        def _replace(match: re.Match) -> str:
            key = f"__CODE_BLOCK_{counter[0]}__"
            code_map[key] = match.group(0)
            counter[0] += 1
            return key

        protected = self._CODE_BLOCK_RE.sub(_replace, text)
        return protected, code_map

    def _restore_code_blocks(self, text: str, code_map: Dict[str, str]) -> str:
        """Restore code block placeholders with original content."""
        for key, value in code_map.items():
            text = text.replace(key, value)
        return text

    def __repr__(self) -> str:
        c = self.config
        return f"DocumentChunker(size={c.chunk_size}, overlap={c.chunk_overlap})"
