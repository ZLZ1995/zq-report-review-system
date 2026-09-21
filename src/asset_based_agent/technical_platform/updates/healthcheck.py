"""Noninteractive candidate-process probe: no login, network or business DB open."""

import json
import os
import re
from pathlib import Path

from ..project_catalog import validate_business_directory
from ..release_info import local_release


def run_healthcheck(request: Path) -> int:
    try:
        with request.open('rb') as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise ValueError('Oversized health request')
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {'schema_version', 'nonce', 'response_path'} or
                type(data['schema_version']) is not int or data['schema_version'] != 1 or
                not isinstance(data['nonce'], str) or not re.fullmatch('[0-9a-f]{64}', data['nonce']) or
                not isinstance(data['response_path'], str)):
            raise ValueError('Invalid health request')
        output = Path(data['response_path'])
        if not output.is_absolute() or output.resolve() != output:
            raise ValueError('Explicit response path required')
        validate_business_directory(output.parent)
        if output.exists():
            raise FileExistsError('Health responses cannot overwrite existing files')
        # Probe actual packaged native dependencies, without a GUI/browser profile.
        from PySide6 import QtWebEngineCore, QtWebEngineWidgets, QtWidgets

        if not all((QtWidgets.QApplication, QtWebEngineCore.QWebEngineProfile,
                    QtWebEngineWidgets.QWebEngineView)):
            raise RuntimeError('Required desktop dependencies unavailable')
        info = local_release()
        if any(skill['status'] not in ('verified', 'builtin') for skill in info['skills']):
            raise ValueError('Packaged resource verification failed')
        payload = {'schema_version': 1, 'nonce': data['nonce'], 'webengine_import': True,
                   'client_version': info['client_version'], 'protocol_version': info['protocol_version'],
                   'local_schema_version': info['local_schema_version'], 'skills': info['skills'],
                   'review_rules_sha256': info['review_rules_sha256']}
        with output.open('x', encoding='utf8') as destination:
            json.dump(payload, destination, ensure_ascii=True, sort_keys=True)
            destination.flush()
            os.fsync(destination.fileno())
        return 0
    except Exception:  # noqa: BLE001 - silent fail-closed health probe, no secrets in GUI/logs.
        return 1

