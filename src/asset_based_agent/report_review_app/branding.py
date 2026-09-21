"""Shared product branding for the report-review desktop applications."""

from __future__ import annotations

import sys
from pathlib import Path


APPLICATION_NAME = "ZQ评估报告审核系统"
CONFIG_TOOL_NAME = f"{APPLICATION_NAME}配置工具"


def application_icon_path() -> Path:
    packaged_root = getattr(sys, "_MEIPASS", None)
    root = (
        Path(packaged_root)
        if packaged_root
        else Path(__file__).resolve().parents[3]
    )
    return root / "assets" / "report_review" / "zq_app_icon.png"
