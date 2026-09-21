import hashlib
import zipfile
from dataclasses import replace

import pytest

from asset_based_agent.technical_platform.updates.local_package import (
    extract_verified_package,
)
from asset_based_agent.technical_platform.updates.manifest import ReleaseManifest


def test_offline_installer_rechecks_bytes_and_never_reuses_tampered_tree(tmp_path):
    package = tmp_path / 'package.zip'
    with zipfile.ZipFile(package, 'w') as output:
        output.writestr('app/client.exe', b'synthetic')
    raw = package.read_bytes()
    release = ReleaseManifest(1, 'test', 10, '0.2.7', 'windows', 'x86_64',
                              'https://test.test/package.zip', len(raw), hashlib.sha256(raw).hexdigest(),
                              1, 1, 1, 30, '1.0.0', 1000, 2000, 'test')
    destination = tmp_path / 'version'
    extract_verified_package(package, release, destination)
    assert (destination / 'app/client.exe').read_bytes() == b'synthetic'
    with pytest.raises(FileExistsError):
        extract_verified_package(package, release, destination)
    with pytest.raises(ValueError):
        extract_verified_package(package, replace(release, sha256='0' * 64), tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()

