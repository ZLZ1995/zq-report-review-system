"""Package the verified client directory without runtime user data."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from asset_based_agent.technical_platform.release_info import CLIENT_VERSION


def main():
    root = Path(__file__).resolve().parents[1]
    parent = root / 'dist/technical_platform'
    folder = parent / 'ZQ技术平台'
    files = [p for p in folder.rglob('*') if p.is_file()]
    if any(p.suffix in {'.db', '.sqlite', '.sqlite3', '.log'} or p.name.startswith('.env') for p in files):
        raise RuntimeError('Unexpected runtime data in package')
    rules = Path('asset_based_agent/technical_platform/review_rules.txt')
    assert (folder / '_internal' / rules).read_bytes() == (root / 'src' / rules).read_bytes()
    for skill in ('valuation-detail-workbook-fill', 'gongshang-change-history-docx'):
        bundle = folder / '_internal/builtin_skills' / skill
        lock = json.loads((bundle / 'template.lock.json').read_text(encoding='utf-8'))
        assert hashlib.sha256((bundle / lock['path']).read_bytes()).hexdigest() == lock['sha256']
    output = parent / f'ZQ-Workspace-{CLIENT_VERSION}-Windows.zip'
    with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(parent))
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(files)
    metadata = {'version': CLIENT_VERSION, 'file': output.name, 'bytes': output.stat().st_size,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'file_count': len(files)}
    output.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
