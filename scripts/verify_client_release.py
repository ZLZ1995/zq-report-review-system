"""Verify a signed client release against the public keys embedded in the client."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from asset_based_agent.technical_platform.updates.manifest import (
    UpdatePolicy,
    verify_manifest,
)
from asset_based_agent.technical_platform.updates.trusted_keys import (
    PUBLIC_KEYS,
    REVOKED_KEY_IDS,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--policy', required=True, type=Path)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    values = json.loads(args.policy.read_text(encoding='utf-8'))
    values['allowed_hosts'] = frozenset(values['allowed_hosts'])
    release = verify_manifest(
        raw,
        keys=PUBLIC_KEYS,
        revoked_keys=REVOKED_KEY_IDS,
        policy=UpdatePolicy(**values),
        now=int(time.time()),
    )
    digest = hashlib.sha256()
    size = 0
    with args.package.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    if size != release.size or digest.hexdigest() != release.sha256:
        raise ValueError('Signed package digest or size mismatch')
    print(json.dumps({
        'version': release.version,
        'sequence': release.sequence,
        'key_id': release.key_id,
        'package_sha256': release.sha256,
        'package_size': release.size,
        'data_schema': [release.data_schema_min, release.data_schema_max],
        'status': 'verified_with_embedded_public_key',
    }))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
