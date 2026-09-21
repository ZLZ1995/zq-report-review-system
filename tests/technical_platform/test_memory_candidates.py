"""G04 记忆候选抽取与写入治理。

验收：敏感样本写入率 0；写入前去重、冲突、敏感扫描；未经确认的项目事实
不进入执行；状态机 proposed/confirmed/revoked/superseded 受控。
"""
import pytest

NOW = '2026-09-18T20:30:00+08:00'


def extract(text, message_id='m1', category_hint=None):
    from asset_based_agent.technical_platform.memory_candidates import (
        extract_candidates,
    )
    return extract_candidates([{'id': message_id, 'role': 'user', 'text': text}],
                              now=NOW, category_hint=category_hint)


# --- 候选抽取 ---

def test_extract_explicit_remember_request():
    candidates = extract('记住以后金额都用万元单位')
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.category == 'user'
    assert candidate.auto_confirmable is True
    assert candidate.source_message_id == 'm1'
    assert '万元' in candidate.text


def test_extract_correction_as_feedback():
    candidates = extract('不是审报告，是审明细表', category_hint='feedback')
    assert candidates[0].category == 'feedback'
    assert candidates[0].auto_confirmable is True


def test_project_fact_requires_confirmation():
    candidates = extract('这个项目的客户是国企', category_hint='project')
    assert candidates[0].category == 'project'
    assert candidates[0].auto_confirmable is False


def test_plain_question_produces_no_candidate():
    assert extract('评估报告包含哪些部分') == []


def test_candidate_carries_provenance_and_confidence():
    candidate = extract('记住以后都用chrome内核')[0]
    assert candidate.status == 'proposed'
    assert 0 < candidate.confidence <= 1
    assert candidate.proposed_at == NOW
    assert candidate.verification_policy


def test_runtime_and_skill_categories_exist():
    from asset_based_agent.technical_platform.memory_candidates import CATEGORIES
    for expected in ('user', 'feedback', 'project', 'reference',
                     'runtime_summary', 'runtime_task', 'runtime_clarification',
                     'runtime_receipt', 'skill_miss', 'skill_false_positive',
                     'skill_acceptance', 'skill_rule_suggestion'):
        assert expected in CATEGORIES


# --- 敏感扫描 ---

@pytest.mark.parametrize('text', ['密码是abc123', '身份证号330106199001011234',
                                  '银行卡号6222020200112233445', 'api_key=sk-abcdef',
                                  '把cookie存下来', 'token: abc.def.ghi'])
def test_sensitive_text_is_flagged(text):
    candidates = extract('记住' + text)
    assert candidates and candidates[0].sensitivity == 'sensitive'


@pytest.mark.parametrize('text', ['记住以后都用万元单位', '记住审核口径以明细表为准'])
def test_normal_text_is_not_sensitive(text):
    assert extract(text)[0].sensitivity == 'normal'


# --- 状态机 ---

@pytest.mark.parametrize('old,new', [('proposed', 'confirmed'), ('proposed', 'revoked'),
                                     ('confirmed', 'revoked'), ('confirmed', 'superseded')])
def test_valid_transitions(old, new):
    from asset_based_agent.technical_platform.memory_candidates import (
        validate_transition,
    )
    assert validate_transition(old, new) is True


@pytest.mark.parametrize('old,new', [('revoked', 'confirmed'), ('superseded', 'proposed'),
                                     ('proposed', 'superseded'), ('revoked', 'proposed')])
def test_invalid_transitions(old, new):
    from asset_based_agent.technical_platform.memory_candidates import (
        validate_transition,
    )
    assert validate_transition(old, new) is False


# --- 写入治理（去重/冲突/敏感） ---

def existing(key='单位偏好', text='金额用万元单位', status='confirmed', scope='user'):
    return {'id': 'mem1', 'key': key, 'text': text, 'status': status, 'scope': scope}


def prepare(candidates, existing_records=(), confirmed_ids=()):
    from asset_based_agent.technical_platform.memory_consolidation import prepare_writes
    return prepare_writes(candidates, existing_records, confirmed_ids=confirmed_ids,
                          now=NOW)


def test_write_dedupes_identical_existing():
    candidate = extract('记住以后金额都用万元单位')[0]
    candidate = candidate.model_copy(update={'key': '单位偏好'})
    plan = prepare([candidate], [existing(text='以后金额都用万元单位')])
    assert plan.writable == () and len(plan.duplicates) == 1


def test_write_conflict_keeps_existing_and_proposes():
    candidate = extract('记住以后金额都用元为单位')[0]
    candidate = candidate.model_copy(update={'key': '单位偏好'})
    plan = prepare([candidate], [existing(text='金额用万元单位')])
    assert plan.writable == () and len(plan.conflicts) == 1
    assert plan.conflicts[0].existing_text == '金额用万元单位'


def test_write_rejects_sensitive_always():
    candidate = extract('记住密码是abc123')[0]
    plan = prepare([candidate], [], confirmed_ids=[candidate.id])
    assert plan.writable == () and len(plan.rejected) == 1
    assert plan.rejected[0].reason == 'sensitive'


def test_project_fact_not_written_without_confirmation():
    candidate = extract('这个项目的客户是国企', category_hint='project')[0]
    plan = prepare([candidate], [])
    assert plan.writable == () and len(plan.pending_confirmation) == 1


def test_explicit_preference_written_when_confirmed():
    candidate = extract('记住以后金额都用万元单位')[0]
    plan = prepare([candidate], [], confirmed_ids=[candidate.id])
    assert len(plan.writable) == 1


def test_unconfirmed_preference_stays_proposed():
    candidate = extract('记住以后金额都用万元单位')[0]
    plan = prepare([candidate], [])
    assert plan.writable == () and len(plan.pending_confirmation) == 1


def test_supersede_marks_old_record():
    from asset_based_agent.technical_platform.memory_consolidation import prepare_writes
    candidate = extract('记住以后金额都用万元单位')[0]
    candidate = candidate.model_copy(update={'key': '单位偏好'})
    plan = prepare_writes([candidate], [existing(text='金额用元为单位')],
                          confirmed_ids=[candidate.id], supersede_conflicts=True, now=NOW)
    assert len(plan.writable) == 1 and plan.superseded_ids == ('mem1',)


def test_sensitive_write_rate_zero_across_samples():
    samples = ['记住密码123', '记住身份证号330106199001011234', '记住token abc']
    rejected = written = 0
    for sample in samples:
        for candidate in extract(sample):
            plan = prepare([candidate], [], confirmed_ids=[candidate.id])
            written += len(plan.writable)
            rejected += len(plan.rejected)
    assert written == 0 and rejected == len(samples)
