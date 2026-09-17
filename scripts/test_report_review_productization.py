"""Run GUI and server regression suites in isolated Python processes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ROOT / "tests" / "report_review_app",
    ROOT / "tests" / "report_review_server",
    ROOT / "tests" / "technical_platform",
)


def announce(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        pass  # Diagnostic logs and JUnit remain authoritative if terminal detaches.


def main(*, artifact_root: Path | None = None) -> int:
    base = (
        artifact_root
        if artifact_root is not None
        else ROOT / "outputs" / "nl_acceptance"
    )
    if not base.is_absolute():
        raise ValueError("Acceptance artifact root must be absolute")
    base = base.resolve()
    if (
        base.drive
        and base.drive.casefold() == os.environ.get("SystemDrive", "C:").casefold()
    ):
        raise ValueError("Acceptance artifacts require a non-system drive")
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    artifacts = base / f"r-{uuid4().hex}"
    artifacts.mkdir(parents=True, exist_ok=False)
    announce(f"Acceptance artifacts: {artifacts}")
    for index, suite in enumerate(SUITES):
        temp_parent = artifacts / str(index)
        temp_parent.mkdir(exist_ok=False)
        try:
            with (artifacts / (suite.name + ".log")).open("wb") as log:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-m",
                        "pytest",
                        str(suite),
                        "-q",
                        "--basetemp",
                        str(temp_parent / "tmp"),
                        f"--junitxml={artifacts / (suite.name + '.xml')}",
                    ],
                    cwd=ROOT,
                    env=environment,
                    check=False,
                    timeout=600,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        except subprocess.TimeoutExpired:
            announce(f"Acceptance suite timed out: {suite.name}")
            return 124
        if result.returncode:
            announce(
                f"Acceptance suite failed: {suite.name}; exit={result.returncode}; see log"
            )
            return result.returncode
        try:
            report = ElementTree.parse(artifacts / (suite.name + ".xml")).getroot()
            suites = (
                [report]
                if report.tag == "testsuite"
                else report.findall(".//testsuite")
            )
            count = sum(int(s.attrib["tests"]) for s in suites)
            if (
                not suites
                or count <= 0
                or count != len(report.findall(".//testcase"))
                or any(
                    int(s.attrib["failures"]) or int(s.attrib["errors"]) for s in suites
                )
                or report.findall(".//testcase/failure")
                or report.findall(".//testcase/error")
            ):
                raise ValueError("Incomplete or failed test report")
        except (OSError, ElementTree.ParseError, KeyError, ValueError):
            announce(f"Acceptance report missing, invalid or failed: {suite.name}")
            return 125
        announce(f"{suite.name}: {count} tests passed")
    announce("report-review-productization-regression: ok")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path)
    raise SystemExit(main(artifact_root=parser.parse_args().artifact_root))
