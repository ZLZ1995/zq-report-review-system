"""Local page identity for upload replay protection, never a model-supplied key.

This is NOT a website business receipt or an authorization to replace files.
OA project routes get a conservative project-wide key (not a work-order ID).
Other sites retain exact HTTPS page identity pending a site-specific adapter.
"""
import re
from hashlib import sha256
from urllib.parse import urlsplit

from .browser_policy import credential_origin


def upload_target_key(url: str) -> str:
    origin = credential_origin(url)
    parsed = urlsplit(url)
    if (not origin or parsed.username is not None or parsed.password is not None
            or any(ord(c) < 32 for c in url)):
        raise ValueError('Safe HTTPS upload page required')
    if origin == 'https://zhongqinoa01.com':
        match = re.fullmatch(r'/projects/([1-9][0-9]*)/flow/?', parsed.path)
        if match is None:
            raise ValueError('OA upload requires an identified project page')
        identity = origin + '/projects/' + match[1]
    else:
        identity = origin + (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
    return sha256(identity.encode('utf-8')).hexdigest()
