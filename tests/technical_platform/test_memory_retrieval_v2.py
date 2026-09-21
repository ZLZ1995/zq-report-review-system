"""G04 记忆召回 v2：≤5 条、陈旧提示、当前证据优先、忽略/撤销/删除。"""
from datetime import datetime, timezone

NOW = datetime(2026, 9, 18, 20, 30, tzinfo=timezone.utc)


def record(identity, key=None, text=None, status='confirmed',
           scope='user', priority=50, valid_until=None, last_verified=None,
           category='user', version=1):
    return {'id': identity, 'key': key or 'k' + identity,
            'text': text or '偏好' + identity, 'status': status,
            'scope': scope, 'priority': priority, 'valid_until': valid_until,
            'last_verified': last_verified, 'category': category, 'version': version}


def make_envelope():
    from asset_based_agent.technical_platform.turn_scope_policy import resolve_scope
    files = [{'id': 'f1', 'name': '明细表.xlsx', 'sha256': 'a' * 64},
             {'id': 'f2', 'name': '旧底稿.docx', 'sha256': 'b' * 64}]
    return resolve_scope(
        owner='alice', project_id='p1', session_id='s1',
        raw_user_text='核对明细表.xlsx，不看旧底稿.docx', selected_ids=['f1'],
        available_files=files, active_model_id='model-a', permission_mode='risk',
        clock=None)


def select(records, **kwargs):
    from asset_based_agent.technical_platform.memory_selector import select_for_turn
    return select_for_turn(records, **kwargs)


def test_recall_never_exceeds_five():
    items = select([record(f'r{i}') for i in range(9)])
    assert len(items) == 5


def test_revoked_and_superseded_never_recalled():
    items = select([record('a', status='revoked'), record('b', status='superseded'),
                    record('c')])
    assert [item.id for item in items] == ['c']


def test_proposed_never_affects_execution():
    items = select([record('a', status='proposed')])
    assert items == []


def test_stale_hint_for_expired_or_old_verified():
    expired = record('a', valid_until='2026-09-01T00:00:00+08:00')
    old = record('b', last_verified='2026-01-01T00:00:00+08:00')
    fresh = record('c', last_verified=NOW.isoformat())
    items = {item.id: item for item in select([expired, old, fresh], now=NOW)}
    assert items['a'].stale is True and items['b'].stale is True
    assert items['c'].stale is False


def test_current_evidence_overrides_conflicting_memory():
    envelope = make_envelope()
    conflict = record('a', text='本次审核请重点参考旧底稿.docx')
    neutral = record('b', text='金额用万元单位')
    items = select([conflict, neutral], envelope=envelope, now=NOW)
    assert [item.id for item in items] == ['b']


def test_ignored_ids_excluded_for_turn():
    items = select([record('a'), record('b')], ignored_ids={'a'})
    assert [item.id for item in items] == ['b']


def test_deterministic_ordering_by_priority_then_id():
    items = select([record('b', priority=90), record('a', priority=90),
                    record('c', priority=10)])
    assert [item.id for item in items] == ['a', 'b', 'c']


def test_recall_item_exposes_source_and_version():
    item = select([record('a', version=3)])[0]
    assert item.version == 3 and item.source_explanation


def test_empty_when_nothing_active():
    assert select([]) == []


# --- 撤销与删除 ---

def test_revoke_stops_recall():
    records = [record('a')]
    from asset_based_agent.technical_platform.memory_consolidation import (
        apply_revocation,
    )
    revoked = apply_revocation(records, 'a', now=NOW)
    assert revoked[0]['status'] == 'revoked'
    assert select(revoked) == []


def test_delete_project_memories_only_touches_project_scope():
    records = [record('p1', scope='project'), record('u1', scope='user'),
               record('p2', scope='project')]
    from asset_based_agent.technical_platform.memory_consolidation import (
        mark_project_memories_deleted,
    )
    remaining = mark_project_memories_deleted(records)
    assert [r['id'] for r in remaining] == ['u1']


def test_conflicting_memory_does_not_override_current_file_evidence():
    envelope = make_envelope()
    memory_claims_excluded = record('a', text='旧底稿.docx是本轮主要依据')
    items = select([memory_claims_excluded], envelope=envelope, now=NOW)
    assert items == []
