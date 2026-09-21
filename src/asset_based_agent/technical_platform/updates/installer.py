"""Locked same-schema installation with real backups and a candidate process probe.

Schema-changing upgrades are rejected. Failed/interrupted activation remains
blocked for recovery; this module never silently restores over newer user writes.
"""

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from ..project_catalog import validate_business_directory
from .database_backup import _digest, backup_database
from .journal import UpdateJournal
from .local_package import extract_verified_package
from .manifest import verify_manifest
from .process_lock import InstallationLock
from .trusted_keys import REVOKED_KEY_IDS


def database_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    for file in (path, Path(str(path) + '-wal')):
        if file.resolve() != file:
            raise ValueError('Database sidecar redirected')
        digest.update(b'present' if file.exists() else b'absent')
        if file.exists():
            with file.open('rb') as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
    return digest.hexdigest()


def probe_candidate(executable: Path, work: Path, release) -> dict:
    nonce = uuid4().hex + uuid4().hex
    request, response = work / 'health-request.json', work / 'health-response.json'
    with request.open('x', encoding='utf8') as stream:
        json.dump({'schema_version': 1, 'nonce': nonce, 'response_path': str(response)}, stream)
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE'}}
    environment.update(TEMP=str(work), TMP=str(work))
    result = subprocess.run([str(executable), '--update-healthcheck', str(request)],
                            cwd=work, env=environment, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=60, check=False,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0:
        raise ValueError('Candidate process health check failed')
    with response.open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('Invalid candidate health response')
    info = json.loads(raw)
    if (not isinstance(info, dict) or info.get('schema_version') != 1 or
            info.get('nonce') != nonce or info.get('webengine_import') is not True):
        raise ValueError('Candidate health response identity mismatch')
    return info


def install_candidate(root: Path, journal: UpdateJournal, signed_manifest: bytes, package: Path,
                      *, databases: tuple[Path, ...], now: int, probe=probe_candidate) -> Path:
    """Trusted updater entry, not an Agent tool. Caller has explicit install consent.

    Every launcher must hold the matching installation runtime lease. Source
    callers can inject a probe only for deterministic tests; CLI always uses the
    native candidate process. Business data is backed up but never migrated here.
    """
    if root.resolve() != root or not root.is_absolute():
        raise ValueError('Explicit installation root required')
    validate_business_directory(root)
    if journal.path != root / 'update-state.sqlite':
        raise ValueError('Journal belongs to another installation')
    if len(set(databases)) != len(databases) or any(
            not p.is_absolute() or p.resolve() != p or p.is_relative_to(root) or not p.is_file()
            for p in databases):
        raise ValueError('Explicit separate project databases required')
    with InstallationLock(root / 'installation-lock.sqlite').installation():
        state = journal.snapshot()
        policy = replace(journal.policy, current_version=state['active_version'], last_sequence=state['sequence'])
        release = verify_manifest(signed_manifest, keys=journal.keys, policy=policy, now=now,
                                  revoked_keys=REVOKED_KEY_IDS)
        token = journal.begin(signed_manifest, now=now)
        try:
            work = root / 'backups' / token
            if work.resolve() != work:
                raise ValueError('Backup location redirected')
            work.mkdir(parents=True, exist_ok=False)
            receipts = []
            before = {path: database_fingerprint(path) for path in databases}
            for path in databases:
                snapshot = backup_database(path, work)
                receipts.append({'source': str(path), 'source_fingerprint': before[path],
                                 'backup': snapshot.path.name, 'sha256': snapshot.sha256, 'size': snapshot.size})
            raw_receipts = json.dumps(receipts, sort_keys=True, ensure_ascii=True).encode('ascii')
            with (work / 'databases.json').open('xb') as stream:
                stream.write(raw_receipts)
                stream.flush()
                os.fsync(stream.fileno())
            journal.backup_verified(token, backup_sha256=hashlib.sha256(raw_receipts).hexdigest())
            versions = root / 'versions'
            if versions.resolve() != versions:
                raise ValueError('Version directory redirected')
            versions.mkdir(exist_ok=True)
            target = extract_verified_package(package, release, versions / release.version)
            executable = target / 'ZQ技术平台' / 'ZQ技术平台.exe'
            if (executable.resolve() != executable or not executable.is_file()
                    or not executable.is_relative_to(target)):
                raise ValueError('Client executable missing from package')
            journal.activating(token)
            info = probe(executable, work, release)
            candidate_schema = info.get('local_schema_version')
            if (info.get('client_version') != release.version or
                    type(info.get('protocol_version')) is not int or info['protocol_version'] != policy.protocol or
                    type(candidate_schema) is not int or candidate_schema < policy.data_schema or
                    not release.data_schema_min <= candidate_schema <= release.data_schema_max):
                raise ValueError('Candidate requires unsupported schema/protocol transition')
            if any(database_fingerprint(path) != fingerprint for path, fingerprint in before.items()):
                raise ValueError('Business database changed during update; manual recovery required')
            journal.complete(token, package_sha256=release.sha256)
            return executable
        except BaseException:
            journal.fail(token)
            raise


def recover_unchanged(root: Path, journal: UpdateJournal) -> None:
    """Restore prior selection only; changed data requires a separate recovery plan.

    The failed candidate is moved to an installation-scoped quarantine, never
    deleted. Backups and live databases are not overwritten by this recovery path.
    """
    if root.resolve() != root or journal.path != root / 'update-state.sqlite':
        raise ValueError('Installation recovery scope mismatch')
    validate_business_directory(root)
    with InstallationLock(root / 'installation-lock.sqlite').installation():
        state = journal.snapshot()
        if state['phase'] == 'activating':
            # Acquiring the exclusive lease proves no prior updater remains.
            # Persist the missing crash transition, then apply the same backup
            # and unchanged-data checks as an ordinary health-check failure.
            journal.fail(state['token'])
            state = journal.snapshot()
        if state['phase'] != 'recovery_required':
            raise ValueError('No recoverable activation recorded')
        token = state['token']
        work = root / 'backups' / token
        if work.resolve() != work:
            raise ValueError('Recovery evidence path redirected')
        with (work / 'databases.json').open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != state['backup_sha256']:
            raise ValueError('Recovery evidence changed')
        receipts = json.loads(raw)
        if not isinstance(receipts, list) or len(receipts) > 1024:
            raise ValueError('Invalid recovery evidence')
        for item in receipts:
            if not isinstance(item, dict) or set(item) != {'source', 'source_fingerprint', 'backup', 'sha256', 'size'}:
                raise ValueError('Invalid database recovery record')
            source, backup = Path(item['source']), work / item['backup']
            if (not source.is_absolute() or source.resolve() != source or source.is_relative_to(root) or
                    backup.parent != work or backup.resolve() != backup or
                    backup.stat().st_size != item['size'] or _digest(backup) != item['sha256'] or
                    database_fingerprint(source) != item['source_fingerprint']):
                raise ValueError('Data changed or backup invalid; automatic recovery refused')
        previous = root / 'versions' / state['active_version']
        failed = root / 'versions' / state['target_version']
        quarantine = root / 'failed-versions' / (token + '-' + state['target_version'])
        for path in (previous, failed, quarantine):
            if path.resolve() != path or not path.is_relative_to(root):
                raise ValueError('Recovery version path redirected')
        if not previous.is_dir():
            raise ValueError('Previous program version missing')
        quarantine.parent.mkdir(exist_ok=True)
        if failed.exists():
            if quarantine.exists():
                raise ValueError('Conflicting failed-version quarantine')
            failed.rename(quarantine)
        elif not quarantine.is_dir():
            raise ValueError('Failed version recovery evidence missing')
        # Still under the installation lock; normal clients cannot begin new work.
        if any(database_fingerprint(Path(item['source'])) != item['source_fingerprint'] for item in receipts):
            raise ValueError('Data changed during recovery')
        journal.recovery_verified(token, backup_sha256=state['backup_sha256'])
