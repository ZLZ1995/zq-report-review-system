"""Run platform regression and optionally render its new desktop shell."""

import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    import pytest

    if ROOT.drive and ROOT.drive.casefold() == os.environ.get('SystemDrive', 'C:').casefold():
        raise ValueError('Acceptance artifacts require a non-system-drive checkout')
    artifacts = ROOT / 'outputs' / 'nl_acceptance' / f'platform-{uuid4().hex}'
    artifacts.mkdir(parents=True, exist_ok=False)
    return pytest.main([
        str(ROOT / "tests" / "technical_platform"), "-q",
        '--basetemp', str(artifacts / 'tmp'),
        f'--junitxml={artifacts / "results.xml"}',
    ])


if __name__ == "__main__":
    raise SystemExit(main())
