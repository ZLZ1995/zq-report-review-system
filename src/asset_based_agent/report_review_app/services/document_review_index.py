"""Compact global index used by deterministic candidate validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .document_extraction_service import DocumentChunk, ExtractedDocument


@dataclass
class DocumentReviewIndex:
    chunks_by_file: dict[str, list[DocumentChunk]] = field(default_factory=dict)
    rows_by_sheet: dict[tuple[str, str], set[int]] = field(default_factory=dict)

    @classmethod
    def build(cls, documents: list[ExtractedDocument]) -> "DocumentReviewIndex":
        index = cls()
        for document in documents:
            file_id = document.source_file.file_id
            index.chunks_by_file[file_id] = list(document.chunks)
            for chunk in document.chunks:
                sheet = chunk.location.table
                cell = chunk.location.cell or ""
                if not sheet or not cell.startswith("row:"):
                    continue
                try:
                    row = int(cell.split(":", 1)[1])
                except ValueError:
                    continue
                index.rows_by_sheet.setdefault((file_id, sheet), set()).add(row)
        return index

    def has_row(self, file_id: str, sheet: str, row: int) -> bool:
        return row in self.rows_by_sheet.get((file_id, sheet), set())

    def search(self, file_id: str, text: str) -> list[DocumentChunk]:
        return [
            chunk
            for chunk in self.chunks_by_file.get(file_id, [])
            if text in chunk.text
        ]
