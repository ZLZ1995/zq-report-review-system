import hashlib
import io
import zipfile
from dataclasses import replace

import httpx
import pytest

from asset_based_agent.technical_platform.storage_layout import StorageLayout
from asset_based_agent.technical_platform.updates.downloader import download_and_stage
from asset_based_agent.technical_platform.updates.manifest import ReleaseManifest


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as output:
        for name, value in entries:
            output.writestr(name, value)
    return buffer.getvalue()


@pytest.fixture
def context(tmp_path):
    program, data = tmp_path / 'program', tmp_path / 'data'
    program.mkdir()
    data.mkdir()
    layout = StorageLayout(program, data, 'test-owner')
    (data / 'history.txt').write_text('preserve', encoding='utf8')
    body = archive([('app/main.exe', b'synthetic'), ('app/resource.txt', b'keep')])
    release = ReleaseManifest(1, 'test', 10, '0.2.7', 'windows', 'x86_64',
                              'https://releases.test/app.zip', len(body),
                              hashlib.sha256(body).hexdigest(), 1, 1, 1, 30,
                              '1.0.0', 1000, 2000, 'test')
    return layout, release, body


def stage(context, handler, **kwargs):
    layout, release, _ = context
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return download_and_stage(release, layout=layout, client=client,
                                  allowed_hosts=frozenset({'releases.test'}), **kwargs)


def test_download_verified_package_without_touching_history_or_program(context):
    layout, _, body = context
    result = stage(context, lambda _: httpx.Response(200, content=body))
    assert (result / 'app/main.exe').read_bytes() == b'synthetic'
    assert (layout.data_root / 'history.txt').read_text() == 'preserve'
    assert list(layout.program_root.iterdir()) == []


@pytest.mark.parametrize('body', [b'corrupt', b'x' * 10000])
def test_corruption_or_oversize_has_no_extracted_files(context, body):
    with pytest.raises(ValueError):
        stage(context, lambda _: httpx.Response(200, content=body))
    assert not list(context[0].update_staging.rglob('main.exe'))


@pytest.mark.parametrize('name', ['../escape', '/escape', 'C:/escape', 'a\\..\\escape',
                                'a:stream', 'CON', 'a/NUL.txt', 'app/trailing.', 'app/end '])
def test_archive_paths_cannot_escape_or_alias_windows_names(context, name):
    layout, release, _ = context
    body = archive([(name, b'bad')])
    release = replace(release, size=len(body), sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError):
        stage((layout, release, body), lambda _: httpx.Response(200, content=body))
    assert not (layout.data_root / 'escape').exists()


def test_case_insensitive_duplicate_members_rejected(context):
    layout, release, _ = context
    body = archive([('app/A', b'1'), ('app/a', b'2')])
    release = replace(release, size=len(body), sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError):
        stage((layout, release, body), lambda _: httpx.Response(200, content=body))


def test_redirect_not_followed_to_untrusted_host(context):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'location': 'https://evil.test/package'})
    with pytest.raises(ValueError):
        stage(context, handler)
    assert requests == ['https://releases.test/app.zip']


def test_cancellation_stops_before_network(context):
    requests = []
    with pytest.raises(InterruptedError):
        stage(context, lambda r: requests.append(r), cancelled=lambda: True)
    assert not requests


def test_insufficient_space_stops_before_network(context, monkeypatch):
    from collections import namedtuple

    from asset_based_agent.technical_platform.updates import downloader
    usage = namedtuple('Usage', 'total used free')(100, 99, 1)
    monkeypatch.setattr(downloader.shutil, 'disk_usage', lambda _: usage)
    with pytest.raises(OSError, match='space'):
        stage(context, lambda _: pytest.fail('must not download'))


def test_platform_credentials_must_not_be_sent_to_download_host(context):
    layout, release, _ = context
    with (
        httpx.Client(headers={'Authorization': 'Bearer synthetic-only'},
                     transport=httpx.MockTransport(lambda _: pytest.fail('credential leak'))) as client,
        pytest.raises(ValueError, match='credential'),
    ):
        download_and_stage(release, layout=layout, client=client,
                           allowed_hosts=frozenset({'releases.test'}))


def test_symlink_member_rejected(context):
    import stat

    layout, release, _ = context
    entry = zipfile.ZipInfo('app/link')
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    body = archive([(entry, b'../../history.txt')])
    release = replace(release, size=len(body), sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError):
        stage((layout, release, body), lambda _: httpx.Response(200, content=body))


def test_disconnect_leaves_no_ready_package(context):
    def handler(_):
        raise httpx.ReadError('synthetic disconnect')
    with pytest.raises(httpx.ReadError):
        stage(context, handler)
    assert not list(context[0].update_staging.rglob('ready'))

