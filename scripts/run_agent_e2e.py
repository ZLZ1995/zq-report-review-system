"""Run one deterministic local Agent lifecycle without calling a paid model.

This entry point validates message intake, structured understanding, explicit
confirmation, read-only execution, post-execution source verification and an
append-only evidence artifact.  It is a harness acceptance probe, not a
semantic-model score and not a release approval.
"""
from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path


def _understanding_payload(pending):
    targets = [item.id for item in pending.request.files]
    return {
        'schema_version': 1,
        'message_intent': 'execute',
        'goal': pending.request.prompt,
        'targets': targets,
        'references': [],
        'excluded': [],
        'constraints': ['只读原文件', '不调用大模型'],
        'deliverables': ['本地预检结果'],
        'missing_inputs': [],
        'evidence_message_ids': [pending.request.message_id],
        'skill_ids': ['review.preflight'],
        'next_action': 'plan',
        'reply': '已识别为本地只读预检；确认后执行。',
    }


def run_e2e(*, workspace: Path, source: Path, message: str, output: Path,
            confirmed: bool) -> dict:
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.execution import execute_task
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.skills import PREFLIGHT, digest
    from asset_based_agent.technical_platform.store import PlatformStore
    from asset_based_agent.technical_platform.task_spec import build_task_spec

    workspace = Path(workspace).resolve()
    source = Path(source).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new evidence filename; existing evidence is never overwritten')
    if confirmed is not True:
        raise PermissionError('本地端到端执行需要明确确认')
    if not source.is_file() or source.suffix.lower() not in {'.docx', '.xlsx', '.pdf'}:
        raise ValueError('E2E source must be an existing DOCX, XLSX or PDF file')
    if not message.strip():
        raise ValueError('E2E message cannot be blank')

    workspace.mkdir(parents=True, exist_ok=False)
    store = PlatformStore(workspace / 'platform.sqlite', 'local-e2e')
    project = store.create_project('Local E2E acceptance')
    session = store.create_session(project)
    source_sha256 = digest(source)
    file_id = store.add_file(project, source, source_sha256)

    controller = AgentController(store)
    pending = controller.prepare(
        session,
        message,
        model_id='deterministic-local-e2e',
        selected_ids=[file_id],
    )
    understanding = controller.complete(pending, _understanding_payload(pending))
    if understanding.next_action != 'plan' or understanding.skill_ids != [PREFLIGHT.id]:
        raise ValueError('Deterministic understanding did not produce the expected preflight plan')

    selected = [item for item in store.files(project) if item['id'] in understanding.targets]
    snapshot = build_task_spec(store, session, message, PREFLIGHT, selected).to_snapshot()
    run_id = store.start_run(session, snapshot)
    PermissionService(store).authorize(run_id, snapshot, confirmed=True)
    result = execute_task(store, run_id, threading.Event(), lambda _message: None)
    if store.run(run_id)['state'] != 'succeeded' or result.get('kind') != 'preflight':
        raise RuntimeError('Local E2E execution did not reach a verified result')
    if digest(source) != source_sha256:
        raise RuntimeError('Source changed during the local E2E run')

    store.append(session, 'assistant', f'本地端到端验收完成。任务编号：{run_id}')
    evidence = {
        'schema_version': 1,
        'mode': 'deterministic_local_harness',
        'status': 'passed',
        'stages': {
            'message': 'passed',
            'understanding': 'passed',
            'confirmation': 'passed',
            'execution': 'passed',
            'verification': 'passed',
            'artifact': 'passed',
        },
        'task_id': run_id,
        'source': {
            'name': source.name,
            'sha256': source_sha256,
            'size_bytes': source.stat().st_size,
        },
        'result': {
            'kind': result['kind'],
            'model_called': result['model_called'],
            'file_count': len(result['files']),
        },
        'limitations': [
            'Uses a deterministic structured understanding fixture.',
            'Does not call a paid model and does not prove semantic accuracy.',
            'Does not approve a client release.',
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    evidence = run_e2e(
        workspace=args.workspace,
        source=args.source,
        message=args.message,
        output=args.output,
        confirmed=args.confirm,
    )
    print(f"Local Agent E2E passed: {evidence['task_id']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
