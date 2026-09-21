"""Stable managed-installation launcher. Does not move or initialize customer data."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main() -> int:
    from asset_based_agent.technical_platform.updates.launcher import launch_selected

    parser = argparse.ArgumentParser()
    parser.add_argument('--installation-root', type=Path,
                        default=Path(sys.executable).parent if getattr(sys, 'frozen', False) else None)
    args = parser.parse_args()
    if args.installation_root is None:
        parser.error('explicit installation root required')
    try:
        return launch_selected(args.installation_root)
    except (OSError, ValueError):
        print('Client launch blocked: installation requires verification or recovery.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

