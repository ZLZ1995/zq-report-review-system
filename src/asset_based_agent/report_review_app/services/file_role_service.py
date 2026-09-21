"""Deterministic first-pass file role classification."""

from __future__ import annotations

from pathlib import Path

from ..domain.enums import FileRole

REPORT_MARKERS = ("评估报告", "资产评估报告", "valuation report")
EXPLANATION_MARKERS = ("评估说明", "资产评估说明", "valuation explanation")
WORKBOOK_MARKERS = ("测算", "评估明细", "申报表", "工作簿", "calculation")


def classify_file_role(path: Path) -> FileRole:
    suffix = path.suffix.lower()
    name = path.stem.lower()
    if suffix == ".pdf":
        return FileRole.REFERENCE_DOCUMENT
    if suffix in {".xlsx", ".xlsm"}:
        if any(marker in name for marker in WORKBOOK_MARKERS):
            return FileRole.CALCULATION_WORKBOOK
        return FileRole.CALCULATION_WORKBOOK
    if suffix == ".docx":
        if any(marker in name for marker in EXPLANATION_MARKERS):
            return FileRole.VALUATION_EXPLANATION
        if any(marker in name for marker in REPORT_MARKERS):
            return FileRole.MAIN_REPORT
    return FileRole.UNKNOWN
