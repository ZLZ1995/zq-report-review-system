"""Package the verified client directory without runtime user data."""
import hashlib
import json
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION
from asset_based_agent.technical_platform.release_info import (
    CLIENT_RELEASE_SEQUENCE,
    CLIENT_VERSION,
    UPDATER_VERSION,
)
from asset_based_agent.technical_platform.updates.journal import UpdateJournal
from asset_based_agent.technical_platform.updates.manifest import UpdatePolicy
from asset_based_agent.technical_platform.updates.process_lock import InstallationLock

DOWNLOAD_HOSTS = [
    'github.com',
    'objects.githubusercontent.com',
    'release-assets.githubusercontent.com',
]

WEBENGINE_HELPER = Path('ZQ技术平台/_internal/PySide6/QtWebEngineProcess.exe')


def archive_name(relative: Path) -> Path:
    return relative.with_suffix('.pending') if relative == WEBENGINE_HELPER else relative


def main(root: Path | None = None):
    explicit_root = root is not None
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    parent = root / 'dist/technical_platform'
    if explicit_root and not parent.exists():
        parent = root
    output = parent / f'ZQ-Workspace-{CLIENT_VERSION}-Windows.zip'
    managed = parent / f'ZQ-Workspace-{CLIENT_VERSION}-Managed-Windows.zip'
    metadata_paths = (output.with_suffix('.json'), managed.with_suffix('.json'))
    if any(path.exists() for path in (output, managed, *metadata_paths)):
        raise FileExistsError('Release artifacts are immutable')
    folder = parent / 'ZQ技术平台'
    files = [p for p in folder.rglob('*') if p.is_file()]
    if any(p.suffix in {'.db', '.sqlite', '.sqlite3', '.log'} or p.name.startswith('.env') for p in files):
        raise RuntimeError('Unexpected runtime data in package')
    rules = Path('asset_based_agent/technical_platform/review_rules.txt')
    assert (folder / '_internal' / rules).read_bytes() == (root / 'src' / rules).read_bytes()
    for skill in ('valuation-detail-workbook-fill', 'gongshang-change-history-docx',
                  'financial-brief-docx'):
        bundle = folder / '_internal/builtin_skills' / skill
        lock = json.loads((bundle / 'template.lock.json').read_text(encoding='utf-8'))
        assert hashlib.sha256((bundle / lock['path']).read_bytes()).hexdigest() == lock['sha256']
    with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            relative = path.relative_to(parent)
            archive.write(path, archive_name(relative))
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(files)
    metadata = {'version': CLIENT_VERSION, 'file': output.name, 'bytes': output.stat().st_size,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'file_count': len(files)}
    output.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    bootstrap = parent / 'bootstrap'
    updater = bootstrap / 'ZQ技术平台更新器.exe'
    launcher = bootstrap / 'ZQ技术平台启动器.exe'
    if not updater.is_file() or not launcher.is_file():
        output.unlink(missing_ok=True)
        output.with_suffix('.json').unlink(missing_ok=True)
        raise FileNotFoundError('Independent updater and launcher are required')
    policy = UpdatePolicy(
        CLIENT_VERSION,
        CLIENT_RELEASE_SEQUENCE,
        'windows',
        'x86_64',
        1,
        SCHEMA_VERSION,
        UPDATER_VERSION,
        frozenset(DOWNLOAD_HOSTS),
    )
    build = root / 'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='managed-release-', dir=build) as temporary:
        staging = Path(temporary)
        policy_values = {**vars(policy), 'allowed_hosts': sorted(policy.allowed_hosts)}
        (staging / 'installation-policy.json').write_text(
            json.dumps(policy_values, sort_keys=True), encoding='utf-8')
        UpdateJournal.initialize(staging / 'update-state.sqlite', policy)
        InstallationLock.initialize(staging / 'installation-lock.sqlite')
        with ZipFile(managed, 'x', ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(launcher, launcher.name)
            archive.write(updater, updater.name)
            for name in ('installation-policy.json', 'update-state.sqlite',
                         'installation-lock.sqlite'):
                archive.write(staging / name, name)
            for path in sorted(files):
                relative = path.relative_to(parent)
                archive.write(
                    path,
                    (Path('versions') / CLIENT_VERSION / archive_name(relative)).as_posix(),
                )
    with ZipFile(managed) as archive:
        assert archive.testzip() is None
    managed_metadata = {
        'version': CLIENT_VERSION,
        'sequence': CLIENT_RELEASE_SEQUENCE,
        'file': managed.name,
        'bytes': managed.stat().st_size,
        'sha256': hashlib.sha256(managed.read_bytes()).hexdigest(),
        'data_schema': SCHEMA_VERSION,
        'kind': 'managed_transition_bundle',
    }
    managed.with_suffix('.json').write_text(
        json.dumps(managed_metadata, indent=2), encoding='utf-8')
    print(json.dumps({'update': metadata, 'managed': managed_metadata}))


if __name__ == '__main__':
    main()
