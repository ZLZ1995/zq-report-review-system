"""Independent updater CLI. Never downloads keys or edits existing user databases."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def read_json(path: Path):
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Updater request exceeds size limit')
    return json.loads(raw)


def main() -> int:
    from asset_based_agent.technical_platform.project_catalog import (
        validate_business_directory,
    )
    from asset_based_agent.technical_platform.updates.installer import (
        install_candidate,
        recover_unchanged,
    )
    from asset_based_agent.technical_platform.updates.journal import UpdateJournal
    from asset_based_agent.technical_platform.updates.manifest import (
        UpdatePolicy,
        version_tuple,
    )
    from asset_based_agent.technical_platform.updates.process_lock import (
        InstallationLock,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('initialize', 'install', 'recover'))
    parser.add_argument('--installation-root', type=Path, required=True)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--databases', type=Path)
    parser.add_argument('--wait-pid', type=int)
    args = parser.parse_args()
    try:
        root = args.installation_root
        if not root.is_absolute() or root.resolve() != root:
            raise ValueError('Explicit installation root required')
        validate_business_directory(root)
        policy_path = root / 'installation-policy.json'
        metadata = read_json(args.policy if args.operation == 'initialize' else policy_path)
        hosts = metadata.get('allowed_hosts')
        if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) for h in hosts):
            raise ValueError('Explicit download hosts required')
        policy = UpdatePolicy(**{**metadata, 'allowed_hosts': frozenset(hosts)})
        version_tuple(policy.current_version)
        if args.operation == 'initialize':
            baseline = root / 'versions' / policy.current_version / 'ZQ����ƽ̨' / 'ZQ����ƽ̨.exe'
            if baseline.resolve() != baseline or not baseline.is_file():
                raise ValueError('Explicit baseline installation required')
            paths = [policy_path, root / 'update-state.sqlite', root / 'installation-lock.sqlite']
            if any(path.exists() for path in paths):
                raise FileExistsError('Installation state already exists; refusing overwrite')
            with policy_path.open('x', encoding='utf8') as output:
                json.dump(metadata, output, sort_keys=True)
            UpdateJournal.initialize(paths[1], policy)
            InstallationLock.initialize(paths[2])
        else:
            journal = UpdateJournal(root / 'update-state.sqlite', policy)
            if args.operation == 'recover':
                if args.wait_pid is not None:
                    raise ValueError('Recovery does not accept a client wait PID')
                recover_unchanged(root, journal)
            else:
                if args.manifest is None or args.package is None or args.databases is None:
                    raise ValueError('Manifest, package and explicit database inventory required')
                if args.wait_pid is not None:
                    from asset_based_agent.technical_platform.updates.process_wait import (
                        wait_for_process_exit,
                    )
                    wait_for_process_exit(args.wait_pid)
                inventory = read_json(args.databases)
                if not isinstance(inventory, list) or len(inventory) > 1024 or any(
                        not isinstance(path, str) for path in inventory):
                    raise ValueError('Invalid database inventory')
                with args.manifest.open('rb') as source:
                    raw = source.read(65537)
                install_candidate(root, journal, raw, args.package,
                                  databases=tuple(Path(path) for path in inventory), now=int(time.time()))
        print(json.dumps({'operation': args.operation, 'status': 'succeeded'}))
        return 0
    except Exception as exc:  # noqa: BLE001 - updater boundary; do not expose local customer paths/secrets.
        print(json.dumps({'operation': args.operation, 'status': 'failed', 'error_type': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
