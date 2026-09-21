"""Cross-round issue reconciliation with stable issue identifiers."""

from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher

from ..domain.enums import IssueStatus
from ..domain.models import IssueHistoryEntry, ReviewIssue


class IssueMatcher:
    def reconcile(
        self,
        previous: list[ReviewIssue],
        current: list[ReviewIssue],
        *,
        round_number: int,
        source_replacements: dict[str, str],
    ) -> list[ReviewIssue]:
        results: list[ReviewIssue] = []
        unmatched_current = list(current)

        for old in previous:
            retained = deepcopy(old)
            if retained.ignored:
                ignored_match, _ = self._best_match(
                    retained,
                    unmatched_current,
                    source_replacements,
                )
                if ignored_match is not None:
                    unmatched_current.remove(ignored_match)
                results.append(retained)
                continue
            match, score = self._best_match(
                retained,
                unmatched_current,
                source_replacements,
            )
            if match is None:
                retained.status = IssueStatus.FIXED
                retained.history.append(
                    IssueHistoryEntry(
                        round_number=round_number,
                        status=IssueStatus.FIXED,
                        note="previous issue was not detected in the new file",
                    )
                )
                results.append(retained)
                continue

            unmatched_current.remove(match)
            original_unchanged = (
                retained.original_text.strip() == match.original_text.strip()
                and retained.location == match.location
            )
            if original_unchanged:
                status = IssueStatus.UNMODIFIED
            elif score >= 0.65:
                status = IssueStatus.INCORRECT_FIX
            else:
                status = IssueStatus.UNCERTAIN
            retained.source_file_id = match.source_file_id
            retained.source_file_name = match.source_file_name
            retained.location = match.location
            retained.original_text = match.original_text
            retained.description = match.description
            retained.evidence = match.evidence
            retained.recommendation = match.recommendation
            retained.confidence = match.confidence
            retained.last_seen_round = round_number
            retained.status = status
            retained.history.append(
                IssueHistoryEntry(
                    round_number=round_number,
                    status=status,
                    note=f"cross-round semantic score={score:.3f}",
                )
            )
            results.append(retained)

        for issue in unmatched_current:
            issue.status = IssueStatus.NEW
            issue.first_seen_round = round_number
            issue.last_seen_round = round_number
            issue.history = [
                IssueHistoryEntry(
                    round_number=round_number,
                    status=IssueStatus.NEW,
                    note="new issue found during full review",
                )
            ]
            results.append(issue)
        return results

    def _best_match(
        self,
        previous: ReviewIssue,
        candidates: list[ReviewIssue],
        source_replacements: dict[str, str],
    ) -> tuple[ReviewIssue | None, float]:
        expected_new_source = source_replacements.get(
            previous.source_file_id,
            previous.source_file_id,
        )
        scored: list[tuple[float, ReviewIssue]] = []
        for candidate in candidates:
            if candidate.source_file_id != expected_new_source:
                continue
            if candidate.category != previous.category:
                continue
            score = _similarity(previous, candidate)
            if score >= 0.45:
                scored.append((score, candidate))
        if not scored:
            return None, 0.0
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]
        if len(scored) > 1 and best_score - scored[1][0] < 0.05:
            return best, min(best_score, 0.64)
        return best, best_score


def _similarity(left: ReviewIssue, right: ReviewIssue) -> float:
    description = SequenceMatcher(
        None,
        left.description.strip(),
        right.description.strip(),
    ).ratio()
    original = SequenceMatcher(
        None,
        left.original_text.strip(),
        right.original_text.strip(),
    ).ratio()
    location = 1.0 if left.location == right.location else 0.0
    return description * 0.45 + original * 0.35 + location * 0.20
