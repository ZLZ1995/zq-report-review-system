"""Navigation boundaries shared by manual and agent-controlled browser surfaces."""

import shlex
from collections.abc import Mapping
from urllib.parse import urlsplit

from PySide6.QtCore import QUrl


def navigation_url(value: str) -> QUrl:
    """Accept explicit web URLs, never local resources or embedded credentials."""
    if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value) or '\\' in value:
        raise ValueError('Invalid browser address')
    if value == 'about:blank':
        return QUrl(value)
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (
            parsed.scheme.lower() not in {'http', 'https'}
            or not parsed.hostname
            or '@' in parsed.netloc
            or (port is not None and port == 0)
        ):
            raise ValueError('Unsupported browser address')
    except ValueError:
        raise ValueError('Invalid browser address') from None
    url = QUrl(value, QUrl.ParsingMode.StrictMode)
    if not url.isValid() or not url.host() or url.userInfo():
        raise ValueError('Invalid browser address')
    return url


def credential_origin(value: str) -> str:
    """Use exact HTTPS origins; paths and default ports are not separate identities."""
    url = navigation_url(value)
    if url.scheme() != 'https':
        raise ValueError('Saved credentials require HTTPS')
    host = url.host().lower()
    if ':' not in host:
        host = bytes(QUrl.toAce(host).data()).decode('ascii').lower()
    if ':' in host:
        host = f'[{host}]'
    port = url.port(443)
    return f'https://{host}' + (f':{port}' if port != 443 else '')


def request_allowed(value: str, *, main_frame: bool) -> bool:
    """Permit ordinary web resources without granting access to host schemes."""
    if not main_frame:
        if value.startswith('data:'):
            return True
        if value.startswith('blob:'):
            value = value[5:]
        elif value.startswith('wss:'):
            value = 'https:' + value[4:]
        elif value.startswith('ws:'):
            value = 'http:' + value[3:]
    try:
        navigation_url(value)
    except ValueError:
        return False
    return True


def download_origin(value: str) -> str:
    """Origin of an HTTPS resource or non-opaque HTTPS blob; not navigation permission."""
    if value.startswith('blob:'):
        inner = navigation_url(value[5:])
        if inner.path() in {'', '/'} or inner.hasQuery() or inner.hasFragment():
            raise ValueError('Invalid generated download resource')
        return credential_origin(value[5:])
    return credential_origin(value)


def check_runtime_environment(environment: Mapping[str, str]) -> None:
    """Refuse unsafe inherited switches rather than silently running without isolation."""
    if environment.get('QTWEBENGINE_DISABLE_SANDBOX') or environment.get('QTWEBENGINE_REMOTE_DEBUGGING'):
        raise ValueError('Unsafe browser environment')
    forbidden = {
        '--no-sandbox', '--disable-setuid-sandbox', '--disable-web-security',
        '--ignore-certificate-errors', '--ignore-certificate-errors-spki-list',
        '--allow-running-insecure-content', '--allow-file-access-from-files',
        '--remote-debugging-port', '--remote-debugging-pipe',
        '--disable-site-isolation-trials', '--unsafely-treat-insecure-origin-as-secure',
    }
    try:
        switches = shlex.split(environment.get('QTWEBENGINE_CHROMIUM_FLAGS', ''))
    except ValueError:
        raise ValueError('Invalid browser switches') from None
    if any(switch.split('=', 1)[0].lower() in forbidden for switch in switches):
        raise ValueError('Unsafe browser switches')
