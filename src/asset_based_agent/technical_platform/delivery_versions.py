"""Locally recorded versions of authorized review deliverables, never originals."""
from pathlib import Path

from .skills import digest


def record_delivery(result, path):
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() not in {'.docx', '.xlsx', '.xlsm'} or not path.is_file():
        raise ValueError('Unsupported review deliverable')
    record = {'sha256': digest(path), 'size': path.stat().st_size}
    versions = result.setdefault('delivery_versions', {})
    if not isinstance(versions, dict):
        raise TypeError('Invalid delivery version metadata')
    if str(path) in versions and versions[str(path)] != record:
        raise ValueError('Delivery version is immutable')
    versions[str(path)] = record


def verify_review_deliveries(result):
    paths = ([result['exported_report']] if result.get('exported_report') else [])
    for batch in result.get('annotations', []):
        paths.extend(batch['files'])
    versions = result.get('delivery_versions', {})
    if not isinstance(versions, dict):
        raise TypeError('Invalid delivery version metadata')
    for raw in paths:
        path = Path(raw)
        if (not path.is_absolute() or path.resolve() != path or not path.is_file()
                or path.suffix.lower() not in {'.docx', '.xlsx', '.xlsm'}):
            raise ValueError('Review deliverable moved, deleted or redirected')
        record = versions.get(str(path))
        if (not isinstance(record, dict) or set(record) != {'sha256', 'size'}
                or type(record['size']) is not int or path.stat().st_size != record['size']
                or digest(path) != record['sha256']):
            raise ValueError('Review deliverable changed or has no recorded version')
