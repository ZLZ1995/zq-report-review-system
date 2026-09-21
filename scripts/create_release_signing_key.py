"""Create an exclusively owned, DPAPI-protected offline release key on Windows.

Never prints private material. A copied KEY file requires the original Windows
identity to decrypt; cross-machine/CI export is deliberately not implemented.
"""

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ENTROPY = b'ZQ-RELEASE-SIGNING-KEY-v1'


def load_key(path: Path) -> tuple[str, Ed25519PrivateKey]:
    import win32crypt

    envelope = json.loads(path.read_bytes())
    if (envelope.get('schema_version') != 1 or
            envelope.get('protection') != 'windows-current-user-dpapi'):
        raise ValueError('Unsupported key envelope')
    _, raw = win32crypt.CryptUnprotectData(
        base64.b64decode(envelope['ciphertext'], validate=True), ENTROPY, None, None, 1)
    return envelope['key_id'], Ed25519PrivateKey.from_private_bytes(raw)


def public_record(path: Path) -> dict:
    key_id, key = load_key(path)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {'key_id': key_id, 'public_key': base64.b64encode(public).decode('ascii'),
            'fingerprint_sha256': hashlib.sha256(public).hexdigest()}


def create_key(path: Path, key_id: str) -> dict:
    import win32api
    import win32con
    import win32crypt
    import win32security
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat

    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key_id):
        raise ValueError('Invalid key ID')
    if not path.is_absolute() or not path.parent.is_dir() or path.resolve() != path:
        raise ValueError('Existing absolute key directory required; links refused')
    if path.drive.casefold() == os.environ.get('SystemDrive', 'C:').casefold():
        raise ValueError('Non-system drive required')
    # Create an empty exclusive file first; restrict ACL before any key is created.
    with path.open('xb') as output:
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        acl = win32security.ACL()
        acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_ALL, sid)
        win32security.SetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        encrypted = win32crypt.CryptProtectData(raw, 'ZQ release signing key', ENTROPY, None, None, 1)
        envelope = {'schema_version': 1, 'key_id': key_id,
                    'protection': 'windows-current-user-dpapi',
                    'ciphertext': base64.b64encode(encrypted).decode('ascii')}
        output.write(json.dumps(envelope, sort_keys=True).encode('ascii'))
        output.flush()
        os.fsync(output.fileno())
    record = public_record(path)
    if record['public_key'] != base64.b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode('ascii'):
        raise ValueError('Key recovery check failed')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-path', required=True, type=Path)
    parser.add_argument('--key-id', required=True)
    args = parser.parse_args()
    print(json.dumps(create_key(args.key_path, args.key_id), sort_keys=True))

