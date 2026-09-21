"""Deterministic text normalization and known-file mention extraction.

No model calls live here. Mentions are resolved only against file names the
current project actually contains; free-text guesses never become scope.
"""
from __future__ import annotations

import re

_WHITESPACE = re.compile(r'\s+')


def normalize_text(raw: str) -> str:
    """Collapse all whitespace runs; keep characters and order intact."""
    if not isinstance(raw, str):
        raise ValueError('本轮要求必须是文本')  # noqa: TRY004 - user-facing boundary
    return _WHITESPACE.sub(' ', raw).strip()


def extract_explicit_references(text: str, known_names) -> tuple[str, ...]:
    """Return known file names literally mentioned in the text.

    Longest names win and their spans are masked so that a shorter name
    contained inside a longer one (明细表.xlsx ⊃ 表.xlsx) is not double
    reported. Matching is case-insensitive for ASCII; CJK is unaffected by
    case folding. Names are returned in order of first appearance.
    """
    if not isinstance(text, str):
        raise ValueError('本轮要求必须是文本')  # noqa: TRY004 - user-facing boundary
    names = sorted({name for name in known_names if isinstance(name, str) and name},
                   key=len, reverse=True)
    lowered = text.casefold()
    spans: list[tuple[int, int, str]] = []
    for name in names:
        needle = name.casefold()
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            end = index + len(needle)
            if not any(index < taken_end and end > taken_start
                       for taken_start, taken_end, _ in spans):
                spans.append((index, end, name))
            start = end
    spans.sort()
    seen, result = set(), []
    for _start, _end, name in spans:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return tuple(result)
