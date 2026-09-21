"""Merge repeated instances of one review defect without losing locations."""

from __future__ import annotations

from .rule_registry import IssueCandidate

_MERGEABLE_CATEGORIES = {"template_residue"}


class IssueAggregationService:
    def aggregate(self, candidates: list[IssueCandidate]) -> list[IssueCandidate]:
        results: list[IssueCandidate] = []
        positions: dict[tuple[str, str, str, str], int] = {}
        for candidate in candidates:
            if candidate.category not in _MERGEABLE_CATEGORIES:
                results.append(candidate)
                continue
            key = (
                candidate.source_file_id,
                candidate.category,
                candidate.rule_id,
                candidate.description,
            )
            if key not in positions:
                candidate.occurrences = [candidate.location]
                positions[key] = len(results)
                results.append(candidate)
                continue
            existing = results[positions[key]]
            if candidate.location not in existing.occurrences:
                existing.occurrences.append(candidate.location)
            for summary in candidate.evidence_summaries:
                if summary not in existing.evidence_summaries:
                    existing.evidence_summaries.append(summary)
        return results
