"""Model-assisted inventory; model output never authorizes arbitrary files or writes."""

from pathlib import Path

from .skills import digest

ROLES = {'balance_sheet', 'trial_balance', 'journal', 'bank_statement', 'other'}

# Server-side material analysis caps the model reply at 2048 tokens; long excerpts
# make the model exceed that budget and the server rejects the truncated JSON.
# Classification evidence (titles and headers) lives in the opening rows, so a
# short per-file excerpt keeps single-call identification reliable.
MAX_FILE_EXCERPT_CHARS = 1500


def resolve_roles(plan, files):
    assignments = plan.get('assignments')
    if not isinstance(assignments, list):
        raise ValueError('资料识别结果无效，请重试')  # noqa: TRY004 - user-facing boundary
    known = {item['id'] for item in files}
    seen, roles = set(), {}
    for item in assignments:
        identity, role = item.get('file_id'), item.get('role')
        if identity not in known or identity in seen or role not in ROLES:
            raise ValueError('资料识别包含未知或重复文件，请重新分析')
        seen.add(identity)
        if role != 'other':
            if role in roles:
                raise ValueError('存在多份同类资料，需要先确认本轮使用的主体和期间')
            roles[role] = identity
    if seen != known:
        raise ValueError('资料识别遗漏文件，请重新分析')
    return roles


class MaterialAnalysisProvider:
    def __init__(self, client, model_id, skill_instructions):
        self.client, self.model_id = client, model_id
        self.skill_instructions = skill_instructions

    def analyze(self, files, run_id, cancel, progress):
        from ..report_review_app.domain.models import SourceFile
        from ..report_review_app.services.document_extraction_service import (
            DocumentExtractionService,
        )
        from ..report_review_app.services.file_role_service import classify_file_role
        from ..report_review_app.services.privacy_filter import PrivacyChunkSelector
        from ..report_review_app.services.task_cancellation import (
            TaskCancelled,
            cancellable_call,
        )

        documents = []
        for item in files:
            if cancel.is_set():
                raise TaskCancelled('资料分析已取消')
            path = Path(item['path'])
            if digest(path) != item['sha256']:
                raise ValueError('资料已变化，请重新添加')
            progress(f'正在只读分析资料：{item["name"]}')
            source = SourceFile(file_id=item['id'], original_name=item['name'], extension=path.suffix.lower(),
                                sha256=item['sha256'], size_bytes=path.stat().st_size, round_number=1,
                                original_path=str(path), role=classify_file_role(path))
            documents.append(cancellable_call(lambda source=source: DocumentExtractionService().extract(source), cancel))
        batches = PrivacyChunkSelector().build_batches(documents)
        texts = {item['id']: [] for item in files}
        for batch in batches:
            for chunk in batch.chunks:
                texts[chunk.source_file_id].append(chunk.text)
        # Bounded visible excerpts only; no paths, binary originals or hidden sheets.
        payload_files = [{'file_id': item['id'], 'name': item['name'],
                          'text': '\n'.join(texts[item['id']])[:MAX_FILE_EXCERPT_CHARS]} for item in files]
        if cancel.is_set():
            raise TaskCancelled('资料分析已取消')
        progress('正在联网验证并调用模型识别资料；识别不会编造缺失数据。')
        payload = {'model_id': self.model_id, 'request_id': 'MATERIAL-' + run_id, 'files': payload_files}
        cancellable = getattr(self.client, 'analyze_materials_cancellable', None)

        def call_model():
            return (cancellable(payload, cancel) if callable(cancellable)
                    else self.client.analyze_materials(payload))

        from ..report_review_app.services.remote_auth_service import (
            RemoteAuthenticationError,
        )
        try:
            plan = cancellable_call(call_model, cancel)
        except RemoteAuthenticationError as exc:
            # The server explicitly asks for a retry when the model reply was
            # truncated or malformed; auth/session failures must not retry.
            if '资料识别结果不完整' not in str(exc) or cancel.is_set():
                raise
            progress('识别结果不完整，正在重试一次。')
            plan = cancellable_call(call_model, cancel)
        return resolve_roles(plan, files), plan
