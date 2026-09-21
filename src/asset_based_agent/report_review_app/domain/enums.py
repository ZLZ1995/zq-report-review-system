"""Stable persisted enums used by report-review projects."""

from __future__ import annotations

from enum import Enum


class StringEnum(str, Enum):
    """String enum with JSON-friendly values."""


class ProjectStatus(StringEnum):
    DRAFT = "draft"
    READY = "ready"
    AUDITING = "auditing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class RoundStatus(StringEnum):
    DRAFT = "draft"
    PREPARING = "preparing"
    EXTRACTING = "extracting"
    RUNNING_LOCAL_RULES = "running_local_rules"
    SELECTING_LLM_CHUNKS = "selecting_llm_chunks"
    RUNNING_LLM_REVIEW = "running_llm_review"
    NORMALIZING_ISSUES = "normalizing_issues"
    MATCHING_PREVIOUS_ISSUES = "matching_previous_issues"
    VERIFYING_SOURCE_HASHES = "verifying_source_hashes"
    COMPLETED = "completed"
    PAUSED_NETWORK_ERROR = "paused_network_error"
    PAUSED_USER_CANCELLED = "paused_user_cancelled"
    FAILED_INPUT = "failed_input"
    FAILED_SCHEMA = "failed_schema"
    FAILED_SOURCE_CHANGED = "failed_source_changed"
    FAILED_INTERNAL = "failed_internal"


class FileRole(StringEnum):
    MAIN_REPORT = "main_report"
    VALUATION_EXPLANATION = "valuation_explanation"
    CALCULATION_WORKBOOK = "calculation_workbook"
    REFERENCE_DOCUMENT = "reference_document"
    UNKNOWN = "unknown"


class IssueStatus(StringEnum):
    NEW = "new"
    UNMODIFIED = "unmodified"
    FIXED = "fixed"
    INCORRECT_FIX = "incorrect_fix"
    UNCERTAIN = "uncertain"
    IGNORED = "ignored"


class RiskLevel(StringEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
