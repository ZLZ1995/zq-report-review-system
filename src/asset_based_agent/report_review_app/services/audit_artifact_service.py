"""Write local, secret-free diagnostics for one audit round."""

from __future__ import annotations

import json
from pathlib import Path

from .document_extraction_service import ExtractedDocument
from .rule_registry import IssueCandidate


class AuditArtifactService:
    def write_extraction(
        self,
        round_dir: Path,
        documents: list[ExtractedDocument],
    ) -> None:
        self._write(
            round_dir / "extraction_manifest.json",
            {
                "documents": [
                    {
                        "file_id": document.source_file.file_id,
                        "file_name": document.source_file.original_name,
                        "mode": document.extraction_mode,
                        "chunk_count": len(document.chunks),
                        "warnings": document.warnings,
                    }
                    for document in documents
                ]
            },
        )

    def write_candidates(
        self,
        round_dir: Path,
        local: list[IssueCandidate],
        llm: list[IssueCandidate],
    ) -> None:
        self._write(
            round_dir / "deterministic_findings.json",
            {"issues": [item.model_dump(mode="json") for item in local]},
        )
        self._write(
            round_dir / "llm_candidates.json",
            {"issues": [item.model_dump(mode="json") for item in llm]},
        )

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
