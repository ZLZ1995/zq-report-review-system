"""S10：Compaction——关键项守恒、无效压缩不得替换、builder 只采信校验过的压缩。"""
from uuid import uuid4

from asset_based_agent.technical_platform.agent_core.compaction import (
    KEY_ITEMS,
    compact_lane,
    extract_key_items,
)
from asset_based_agent.technical_platform.agent_core.context_builder import (
    ContextBuilder,
)
from asset_based_agent.technical_platform.agent_core.fakes import InMemorySessionRepo


def make_repo():
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话',
                        permission_mode='assisted')
    return repo


def add_turn(repo, user, assistant, lane='main'):
    operation = repo.begin_operation('s1', lane, user_text=user,
                                     request_id=uuid4().hex)
    entry = repo.append_entry('s1', lane, 'assistant_message',
                              {'text': assistant}, operation_id=operation.id)
    repo.complete_operation(operation.id, assistant_entry_id=entry.id,
                            turn_id=None)
    return operation


def build_lane(repo, turns=4):
    operations = []
    for index in range(turns):
        operations.append(add_turn(repo, f'目标问题{index}', f'进展回答{index}'))
    return operations


def test_key_items_catalog_is_stable():
    assert KEY_ITEMS == ('user_goal', 'file_scope', 'exclusions',
                         'permission_limits', 'confirmed_facts',
                         'open_questions', 'artifact_refs', 'progress')


def test_extract_key_items_from_entries():
    repo = make_repo()
    operation = add_turn(repo, '帮我审核报告', '好的，先解析文件')
    repo.bind_file(operation.id, 'file-a', 'explicit_upload', sha256='a' * 64)
    entries = repo.entries('s1', 'main')
    bindings = repo.operation_files(operation.id)
    items = extract_key_items(entries, bindings=bindings,
                              permission_mode='assisted')
    assert items['user_goal'] == '帮我审核报告'
    assert items['file_scope'] == ['file-a']
    assert items['permission_limits'] == 'assisted'
    assert items['progress'] == '好的，先解析文件'


def test_compaction_roundtrip_and_builder_uses_valid_compaction():
    repo = make_repo()
    build_lane(repo, turns=4)
    boundary = repo.entries('s1', 'main')[3]  # 压缩前两轮
    outcome = compact_lane(repo, 's1', 'main', end_entry_id=boundary.id,
                           permission_mode='assisted')
    assert outcome['valid'] is True
    record = repo.latest_compaction('s1', 'main')
    assert record is not None and record['source_end_entry_id'] == boundary.id
    # builder：压缩摘要进入上下文，被覆盖的旧轮次不再全文出现
    # （关键项允许出现在摘要里：用户目标=目标问题0、当前进度=进展回答1）
    operation = repo.begin_operation('s1', 'main', user_text='压缩后的新问题',
                                     request_id=uuid4().hex)
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    joined = '\n'.join(m['payload'].get('text', '') for m in built.messages)
    assert built.report['compaction_used'] is True
    assert '目标问题1' not in joined and '进展回答0' not in joined
    assert '用户目标：目标问题0' in joined  # 关键约束经摘要保留
    assert '目标问题3' in joined and '压缩后的新问题' in joined


def test_compaction_invalid_when_key_item_dropped():
    repo = make_repo()
    build_lane(repo, turns=3)
    boundary = repo.entries('s1', 'main')[1]

    def lossy_summarizer(items, entries):
        dropped = dict(items)
        dropped['user_goal'] = ''  # 摘要丢失用户目标
        return {'text': '有损摘要', 'key_items': dropped}

    outcome = compact_lane(repo, 's1', 'main', end_entry_id=boundary.id,
                           permission_mode='assisted',
                           summarizer=lossy_summarizer)
    assert outcome['valid'] is False
    assert 'user_goal' in outcome['missing']
    assert repo.latest_compaction('s1', 'main') is None  # 无效压缩不得保存


def test_compaction_preserves_all_present_key_items():
    repo = make_repo()
    first = add_turn(repo, '审核这份报告', '已解析，发现 2 个待确认问题？')
    repo.bind_file(first.id, 'file-x', 'explicit_upload', sha256='x' * 64)
    fact_id = repo.propose_fact('p1', 'project', '口径', '保守')
    repo.set_fact_status(fact_id, 'confirmed')
    boundary = repo.entries('s1', 'main')[-1]
    entries = repo.entries('s1', 'main')
    before = extract_key_items(entries, bindings=repo.operation_files(first.id),
                               permission_mode='assisted')
    outcome = compact_lane(repo, 's1', 'main', end_entry_id=boundary.id,
                           permission_mode='assisted')
    assert outcome['valid'] is True
    after = outcome['key_items']
    for key in KEY_ITEMS:
        if before[key]:
            assert after[key] == before[key], key


def test_builder_ignores_compaction_with_tampered_source_hash():
    repo = make_repo()
    build_lane(repo, turns=3)
    entries = repo.entries('s1', 'main')
    summary = repo.append_entry('s1', 'main', 'context_summary',
                                {'text': '伪造摘要', 'key_items': {}})
    repo.save_compaction('s1', 'main',
                         source_start_entry_id=entries[0].id,
                         source_end_entry_id=entries[1].id,
                         source_sha256='0' * 64,  # 与真实源不一致
                         summary_entry_id=summary.id)
    operation = repo.begin_operation('s1', 'main', user_text='新问题',
                                     request_id=uuid4().hex)
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    joined = '\n'.join(m['payload'].get('text', '') for m in built.messages)
    assert built.report['compaction_used'] is False
    assert '伪造摘要' not in joined
    assert '目标问题0' in joined  # 压缩被忽略，回到完整历史
