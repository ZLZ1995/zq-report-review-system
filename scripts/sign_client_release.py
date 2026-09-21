"""Offline Windows signer; requires an operator-supplied protected KEY file.

Does not generate keys, upload anything, or activate release channels.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def read_object(path: Path) -> dict:
    with path.open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('Signing metadata too large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError('Signing metadata object required')
    return value


def main() -> int:
    from create_release_signing_key import load_key

    from asset_based_agent.technical_platform.updates.manifest import UpdatePolicy
    from asset_based_agent.technical_platform.updates.signing import sign_release

    parser = argparse.ArgumentParser()
    for name in ('key-path', 'package', 'metadata', 'policy', 'output'):
        parser.add_argument(f'--{name}', required=True, type=Path)
    args = parser.parse_args()
    try:
        key_id, key = load_key(args.key_path)
        metadata = read_object(args.metadata)
        if metadata.get('key_id') != key_id:
            raise ValueError('Metadata and key ID do not match')
        policy = read_object(args.policy)
        hosts = policy.get('allowed_hosts')
        if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) for h in hosts):
            raise ValueError('Explicit release download hosts required')
        policy['allowed_hosts'] = frozenset(hosts)
        sign_release(metadata, package=args.package, private_key=key, output=args.output,
                     policy=UpdatePolicy(**policy), now=int(time.time()))
        print(json.dumps({'key_id': key_id, 'version': metadata['version'],
                          'manifest_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))
        return 0
    except Exception as exc:  # noqa: BLE001 - secret-handling CLI boundary; fail closed without provider text.
        # Deliberately avoid serializing exceptions from key providers/DPAPI.
        print(f'Release signing refused ({type(exc).__name__}); no release activated.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

