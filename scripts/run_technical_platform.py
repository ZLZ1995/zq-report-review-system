"""Launch the isolated project-oriented platform preview."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == '--builtin-skill-worker':
        from asset_based_agent.technical_platform.generation_worker import main
        raise SystemExit(main(sys.argv[2]))
    else:
        from asset_based_agent.technical_platform.app import main
        raise SystemExit(main())
