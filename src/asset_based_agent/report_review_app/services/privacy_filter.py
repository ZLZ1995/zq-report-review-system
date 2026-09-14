"""Build bounded text batches without sending original binary files."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import FileRole
from .document_extraction_service import DocumentChunk, ExtractedDocument


class ReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    chunks: list[DocumentChunk] = Field(default_factory=list)
    character_count: int = Field(ge=0)


class PrivacyChunkSelector:
    def __init__(self, max_batch_characters: int = 12_000) -> None:
        if max_batch_characters < 500:
            raise ValueError("max_batch_characters is too small")
        self.max_batch_characters = max_batch_characters

    def build_batches(self, documents: list[ExtractedDocument]) -> list[ReviewBatch]:
        batches: list[ReviewBatch] = []
        current: list[DocumentChunk] = []
        current_size = 0
        for document in documents:
            for chunk in document.chunks:
                if (
                    chunk.role == FileRole.CALCULATION_WORKBOOK
                    and chunk.reference_only
                ):
                    continue
                text = chunk.text.strip()
                if not text:
                    continue
                safe_chunk = chunk.model_copy(update={"text": text[: self.max_batch_characters]})
                chunk_size = len(safe_chunk.text)
                if current and current_size + chunk_size > self.max_batch_characters:
                    batches.append(self._batch(len(batches) + 1, current, current_size))
                    current = []
                    current_size = 0
                current.append(safe_chunk)
                current_size += chunk_size
        if current:
            batches.append(self._batch(len(batches) + 1, current, current_size))
        return batches

    @staticmethod
    def _batch(index: int, chunks: list[DocumentChunk], size: int) -> ReviewBatch:
        return ReviewBatch(
            batch_id=f"BATCH-{index:04d}",
            chunks=list(chunks),
            character_count=size,
        )
