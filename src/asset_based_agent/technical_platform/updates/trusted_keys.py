"""Public release trust roots shipped with the client; never fetched unsigned.

Only public keys belong here. Rotation must first ship the next public key in a
release signed by an existing trusted key. Revocations override the key map.
"""

import base64
from types import MappingProxyType

PUBLIC_KEYS = MappingProxyType({
    'zq-release-20260917': base64.b64decode('GwMV2oe4mWUq9MQDsfkeGLRMGWFoMhTiAngTSUrsqlU='),
})
REVOKED_KEY_IDS: frozenset[str] = frozenset()

