"""Windows current-user DPAPI only; no portable/plaintext fallback.

Context is domain separation, not a second secret. This does not defend against
malware already running as the same Windows user or a compromised host.
"""
from hashlib import sha256


def _transform(payload: bytes, context: bytes, *, decrypt: bool) -> bytes:
    if not payload or not context or len(payload) > 65536:
        raise ValueError('Local credential protection failed')
    try:
        import pywintypes
        import win32crypt
    except ImportError:
        raise ValueError('Local credential protection unavailable') from None
    entropy = sha256(b'ZQ-browser-credentials-v1\x00' + context).digest()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN=1; deliberately not LOCAL_MACHINE=4.
        if decrypt:
            result = win32crypt.CryptUnprotectData(payload, entropy, None, None, 1)[1]
        else:
            result = win32crypt.CryptProtectData(payload, 'ZQ website credential', entropy, None, None, 1)
        return bytes(result)
    except (pywintypes.error, OSError, ValueError, TypeError):
        raise ValueError('Local credential protection failed') from None


def protect(payload: bytes, context: bytes) -> bytes:
    return _transform(payload, context, decrypt=False)


def unprotect(payload: bytes, context: bytes) -> bytes:
    return _transform(payload, context, decrypt=True)
