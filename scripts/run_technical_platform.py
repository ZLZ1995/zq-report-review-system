"""Launch the isolated project-oriented platform preview."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from asset_based_agent.technical_platform.app import main

if __name__ == "__main__":
    raise SystemExit(main())
