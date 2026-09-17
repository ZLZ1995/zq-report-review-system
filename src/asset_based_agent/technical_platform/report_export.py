"""Adapt a completed workspace review to the existing standard Word template."""
import json
import os
import tempfile
from pathlib import Path

from ..report_review_app.domain.models import AuditProject, ReviewIssue
from ..report_review_app.services.report_export_service import ReportExportService


def export_review(store, run_id: str, destination: Path) -> Path:
    run = store.run(run_id)
    result = json.loads(run['result'] or '{}')
    if run['state'] != 'succeeded' or result.get('kind') != 'review':
        raise ValueError('仅已完成的模型审核可导出标准审核报告。')
    destination = Path(destination).with_suffix('.docx').resolve()
    snapshot = json.loads(run['snapshot'])
    project_id = store.session(run['session'])['project']
    protected = [*snapshot.get('files', []), *store.files(project_id)]
    for item in protected:
        source = Path(item['path']).resolve()
        if source == destination or (destination.exists() and source.exists() and os.path.samefile(source, destination)):
            raise ValueError('不能覆盖送审原文件，请选择其他文件名。')
    if destination.exists():
        raise ValueError('为保护已有文件，请选择尚不存在的新文件名。')
    project = AuditProject(project_id=project_id, name=store.project(project_id)['name'], project_path=str(destination.parent), current_round=1)
    issues = []
    for index, item in enumerate(result.get('issues', []), 1):
        pending = item.get('requires_verification') or '待核实' in item.get('description', '').split('】', 1)[0]
        issues.append(ReviewIssue(
            issue_id=f'{run_id}-{index}', fingerprint=f'{run_id}-{index}',
            source_file_id=item['source_file_id'], source_file_name=item['source_file_name'],
            category=item['category'], risk_level=item['risk_level'],
            status='uncertain' if pending else 'new', location=item.get('location', {}),
            description=item['description'], recommendation=item.get('recommendation', ''),
            original_text=item.get('original_text', '') or '\n'.join(item.get('evidence_summaries', [])), confidence=item.get('confidence', 0),
            first_seen_round=1, last_seen_round=1, origin='model', evidence_state='unverified',
        ))
    service = ReportExportService()
    summary = service._summary(project, 1, issues)
    summary['files'] = [{'file_id': item.get('id', ''), 'name': item.get('name', ''), 'role': '送审资料'} for item in snapshot.get('files', [])]
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.docx', dir=destination.parent)
    os.close(fd)
    try:
        service._write_docx(Path(temporary), project, summary, issues)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    result['exported_report'] = str(destination)
    from .delivery_versions import record_delivery
    record_delivery(result, destination)
    store.save_result(run_id, result)
    return destination
