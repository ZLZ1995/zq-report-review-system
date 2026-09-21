"""Restricted read-only adapter around the configured review model."""

from __future__ import annotations

from collections.abc import Callable
from inspect import signature

from .document_extraction_service import ExtractedDocument
from .privacy_filter import PrivacyChunkSelector
from .review_llm_client import ReviewLlm
from .rule_registry import IssueCandidate


class ReportReviewAgent:
    def __init__(
        self,
        llm: ReviewLlm,
        selector: PrivacyChunkSelector,
    ) -> None:
        self.llm = llm
        self.selector = selector

    def review(
        self,
        documents: list[ExtractedDocument],
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[IssueCandidate]:
        batches = self.selector.build_batches(documents)
        review_batches = self.llm.review_batches
        if (
            progress_callback is not None
            and "progress_callback" in signature(review_batches).parameters
        ):
            return review_batches(
                batches,
                progress_callback=progress_callback,
            )
        return review_batches(batches)
