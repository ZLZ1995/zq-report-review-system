"""Native upload attempt history. This is not evidence of website success."""
import html
import json
import re


def upload_history(store, run_id):
    store.run(run_id)  # Owner validation applies even when there are no records.
    with store.connect() as db:
        rows = db.execute(
            'SELECT a.receipt,a.state,a.created,a.metadata FROM browser_upload_attempts a '
            'JOIN runs r ON r.id=a.run JOIN sessions s ON s.id=r.session '
            'JOIN projects p ON p.id=s.project WHERE a.run=? AND p.owner=? '
            'ORDER BY a.created,a.receipt', (run_id, store.owner)).fetchall()
    records = []
    for row in rows:
        item = dict(row)
        raw = json.loads(item['metadata']) if item['metadata'] else None
        # Legacy attempts deliberately remain unknown, without invented metadata.
        if raw is not None:
            required = {'origin', 'object_label', 'name', 'size', 'sha256'}
            if (not isinstance(raw, dict) or not required <= set(raw)
                    or set(raw) - required - {'target_key'}):
                raise ValueError('Invalid upload history metadata')
            if not isinstance(raw.get('target_key', ''), str) or not re.fullmatch(r'(?:[0-9a-f]{64})?', raw.get('target_key', '')):
                raise ValueError('Invalid upload target identity')
            from ..browser_contracts import UploadArtifact
            from .browser_policy import credential_origin
            UploadArtifact.model_validate({'id': row['receipt'],
                                          **{k: raw[k] for k in ('name', 'size', 'sha256')}})
            if (credential_origin(raw['origin']) != raw['origin']
                    or not isinstance(raw['object_label'], str)
                    or not 1 <= len(raw['object_label']) <= 512):
                raise ValueError('Invalid upload history target')
        item['metadata'] = raw
        records.append(item)
    return records


def upload_history_html(store, run_id):
    blocks = []
    for row in upload_history(store, run_id):
        metadata = row['metadata']
        lines = ['上传结果待核对', '任务：' + run_id,
                 '已记录一次上传尝试；不代表网站已保存。请先核对网站记录，不要重复上传。']
        if metadata:
            lines += [metadata['origin'], '业务对象：' + metadata['object_label'],
                      metadata['name'] + ' · ' + str(metadata['size']) + ' 字节',
                      'SHA256：' + metadata['sha256']]
        else:
            lines += ['旧版记录缺少文件及对象摘要，请结合当时任务核对。']
        lines += ['记录时间：' + row['created']]
        blocks.append('<p>' + '<br>'.join(html.escape(line) for line in lines) + '</p>')
    return ''.join(blocks)
