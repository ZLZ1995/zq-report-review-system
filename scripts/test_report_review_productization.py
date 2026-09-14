"""Run GUI and server regression suites in isolated Python processes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ROOT / "tests" / "report_review_app",
    ROOT / "tests" / "report_review_server",
)


def main() -> int:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for suite in SUITES:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(suite), "-q"],
            cwd=ROOT,
            env=environment,
            check=False,
        )
        if result.returncode:
            return result.returncode
    print("report-review-productization-regression: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
