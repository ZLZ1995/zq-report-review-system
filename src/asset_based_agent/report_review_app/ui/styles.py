"""Shared status labels and translucent card colors."""

from __future__ import annotations

from ..domain.enums import IssueStatus

STATUS_LABELS = {
    IssueStatus.NEW: "本轮新发现",
    IssueStatus.UNMODIFIED: "未修改",
    IssueStatus.FIXED: "已正确修改",
    IssueStatus.INCORRECT_FIX: "修改后仍有错误",
    IssueStatus.UNCERTAIN: "待人工核实",
    IssueStatus.IGNORED: "已忽略",
}

STATUS_COLORS = {
    IssueStatus.NEW: "rgba(220, 60, 60, 128)",
    IssueStatus.UNMODIFIED: "rgba(220, 60, 60, 128)",
    IssueStatus.FIXED: "rgba(45, 170, 90, 128)",
    IssueStatus.INCORRECT_FIX: "rgba(235, 140, 40, 128)",
    IssueStatus.UNCERTAIN: "rgba(235, 140, 40, 128)",
    IssueStatus.IGNORED: "rgba(130, 130, 130, 128)",
}
