"""Deterministic validation for model-proposed review candidates."""

from __future__ import annotations

import re

from .document_extraction_service import ExtractedDocument
from .rule_registry import IssueCandidate

_ROW_NUMBER = re.compile(r"\d+")


class CandidateValidationService:
    def accepts(
        self,
        candidate: IssueCandidate,
        documents: list[ExtractedDocument],
    ) -> bool:
        if candidate.rule_id != "llm.review.v1":
            return True
        if candidate.claim_type == "missing_row":
            return self._missing_rows_are_absent(candidate, documents)
        if candidate.requires_global_search and not candidate.claim_type:
            return False
        if self._unsupported_zero_balance_inference(candidate, documents):
            return False
        return not self._legacy_missing_row_claim_is_refuted(candidate, documents)

    def _unsupported_zero_balance_inference(
        self,
        candidate: IssueCandidate,
        documents: list[ExtractedDocument],
    ) -> bool:
        if candidate.category != "data_inconsistency":
            return False
        row = self._candidate_row(candidate)
        if row is None or not candidate.location.table:
            return False
        chunk = self._location_chunk(candidate, documents)
        if chunk is None or not self._all_numeric_cached_values_are_zero(chunk):
            return False
        description = candidate.description
        presence_inference = (
            "表明应存在" in description or "暗示存在" in description
        )
        missing_output_columns = (
            "缺少" in description
            and any(
                marker in description
                for marker in ("评估价值", "增值额", "增值率", "列公式")
            )
        )
        return presence_inference or missing_output_columns

    @staticmethod
    def _candidate_row(candidate: IssueCandidate) -> int | None:
        cell = candidate.location.cell or ""
        if not cell.startswith("row:"):
            return None
        value = cell.split(":", 1)[1].split(",", 1)[0].strip()
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _location_chunk(
        candidate: IssueCandidate,
        documents: list[ExtractedDocument],
    ):
        for document in documents:
            if document.source_file.file_id != candidate.source_file_id:
                continue
            for chunk in document.chunks:
                if (
                    chunk.location.table == candidate.location.table
                    and chunk.location.cell == candidate.location.cell
                ):
                    return chunk
        return None

    @staticmethod
    def _all_numeric_cached_values_are_zero(chunk) -> bool:
        numeric = [
            float(value)
            for value in chunk.cached_values.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        return bool(numeric) and all(abs(value) < 1e-12 for value in numeric)

    def _missing_rows_are_absent(
        self,
        candidate: IssueCandidate,
        documents: list[ExtractedDocument],
    ) -> bool:
        if not candidate.target_sheet or not candidate.target_rows:
            return False
        observed = self._observed_rows(
            candidate.source_file_id,
            candidate.target_sheet,
            documents,
        )
        return not set(candidate.target_rows).intersection(observed)

    def _legacy_missing_row_claim_is_refuted(
        self,
        candidate: IssueCandidate,
        documents: list[ExtractedDocument],
    ) -> bool:
        if "不存在" not in candidate.description or not candidate.location.table:
            return False
        prefix = candidate.description.split("不存在", 1)[0]
        claimed = {int(value) for value in _ROW_NUMBER.findall(prefix)}
        observed = self._observed_rows(
            candidate.source_file_id,
            candidate.location.table,
            documents,
        )
        return bool(claimed.intersection(observed))

    @staticmethod
    def _observed_rows(
        source_file_id: str,
        sheet: str,
        documents: list[ExtractedDocument],
    ) -> set[int]:
        rows: set[int] = set()
        for document in documents:
            if document.source_file.file_id != source_file_id:
                continue
            for chunk in document.chunks:
                if chunk.location.table != sheet:
                    continue
                cell = chunk.location.cell or ""
                if not cell.startswith("row:"):
                    continue
                try:
                    rows.add(int(cell.split(":", 1)[1]))
                except ValueError:
                    continue
        return rows
