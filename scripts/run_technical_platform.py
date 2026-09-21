"""Launch the isolated project-oriented platform preview."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if __name__ == "__main__":
    if getattr(sys, 'frozen', False):
        from asset_based_agent.technical_platform.updates.runtime_files import (
            configure_webengine_helper,
        )
        configure_webengine_helper(Path(sys.executable).resolve().parent)
    if len(sys.argv) == 3 and sys.argv[1] == '--update-healthcheck':
        from asset_based_agent.technical_platform.updates.healthcheck import (
            run_healthcheck,
        )
        raise SystemExit(run_healthcheck(Path(sys.argv[2])))
    elif len(sys.argv) == 3 and sys.argv[1] == '--builtin-skill-worker':
        from asset_based_agent.technical_platform.generation_worker import main
        from asset_based_agent.technical_platform.updates.launcher import run_managed
        raise SystemExit(run_managed(lambda: main(sys.argv[2])))
    else:
        from asset_based_agent.technical_platform.app import main
        from asset_based_agent.technical_platform.updates.launcher import run_managed
        raise SystemExit(run_managed(main))
