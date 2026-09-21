import hashlib

import pytest

from asset_based_agent.technical_platform.updates.trusted_keys import (
    PUBLIC_KEYS,
    REVOKED_KEY_IDS,
)


def test_embedded_root_matches_approved_public_fingerprint():
    public = PUBLIC_KEYS['zq-release-20260917']
    assert len(public) == 32
    assert hashlib.sha256(public).hexdigest() == 'eaabb1fd4cebe82e55227be86fcc00ed21dbbcf2427359f8dd2b8afd6ecff378'
    assert 'zq-release-20260917' not in REVOKED_KEY_IDS
    with pytest.raises(TypeError):
        PUBLIC_KEYS['untrusted-network-key'] = b'x' * 32

