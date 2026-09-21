"""G10 故障演练矩阵：12 个场景的明确终态、恢复策略和用户可理解提示。

验收：断网、余额不足、模型超时、响应丢失、客户端重启、Office 崩溃、
WPS 不可用、文件被占用、浏览器页面变化、用户取消、Skill 冲突和损坏 ZIP
全部有明确终态、恢复策略和中文用户提示；运行时场景有 Journal 证据。
"""

REQUIRED_SCENARIOS = ('offline', 'insufficient_balance', 'model_timeout',
                      'response_lost', 'client_restart', 'office_crash',
                      'wps_unavailable', 'file_locked', 'page_changed',
                      'user_cancel', 'skill_conflict', 'corrupt_zip')

TERMINAL_VOCABULARY = ('failed', 'cancelled', 'recovered', 'manual_review',
                       'rejected', 'waiting')


def run(scenario, tmp_path):
    from asset_based_agent.technical_platform.failure_drills import run_drill
    return run_drill(scenario, tmp_path)


def assert_well_formed(outcome):
    assert outcome.terminal_state in TERMINAL_VOCABULARY
    assert outcome.recovery
    assert outcome.user_message
    assert outcome.evidence


def test_matrix_covers_twelve_required_scenarios():
    from asset_based_agent.technical_platform.failure_drills import SCENARIOS
    assert tuple(SCENARIOS) == REQUIRED_SCENARIOS


def test_offline_retries_then_fails_with_guidance(tmp_path):
    outcome = run('offline', tmp_path)
    assert outcome.terminal_state == 'failed'
    assert 'node_retrying' in outcome.evidence
    assert '网络' in outcome.user_message
    assert_well_formed(outcome)


def test_model_timeout_retries_then_fails(tmp_path):
    outcome = run('model_timeout', tmp_path)
    assert outcome.terminal_state == 'failed'
    assert 'node_retrying' in outcome.evidence
    assert '超时' in outcome.user_message
    assert_well_formed(outcome)


def test_insufficient_balance_fails_without_retry(tmp_path):
    outcome = run('insufficient_balance', tmp_path)
    assert outcome.terminal_state == 'failed'
    assert 'node_retrying' not in outcome.evidence
    assert '余额' in outcome.user_message
    assert_well_formed(outcome)


def test_response_lost_reconciles_by_client_job_id(tmp_path):
    outcome = run('response_lost', tmp_path)
    assert outcome.terminal_state == 'recovered'
    assert '不重复扣费' in outcome.user_message
    assert_well_formed(outcome)


def test_response_lost_unknown_goes_manual_review(tmp_path):
    from asset_based_agent.technical_platform.failure_drills import run_drill
    outcome = run_drill('response_lost', tmp_path, remote_known=False)
    assert outcome.terminal_state == 'manual_review'
    assert_well_formed(outcome)


def test_client_restart_resumes_without_duplicate_work(tmp_path):
    outcome = run('client_restart', tmp_path)
    assert outcome.terminal_state == 'recovered'
    assert '恢复' in outcome.user_message
    assert_well_formed(outcome)


def test_office_crash_goes_manual_review_never_replay(tmp_path):
    outcome = run('office_crash', tmp_path)
    assert outcome.terminal_state == 'manual_review'
    assert '人工' in outcome.user_message
    assert_well_formed(outcome)


def test_wps_unavailable_falls_back_to_office(tmp_path):
    outcome = run('wps_unavailable', tmp_path)
    assert outcome.terminal_state == 'recovered'
    assert 'Office' in outcome.user_message
    assert_well_formed(outcome)


def test_no_office_backend_fails_clearly(tmp_path):
    from asset_based_agent.technical_platform.failure_drills import run_drill
    outcome = run_drill('wps_unavailable', tmp_path, available_backends=())
    assert outcome.terminal_state == 'failed'
    assert_well_formed(outcome)


def test_file_locked_fails_with_recovery_hint(tmp_path):
    outcome = run('file_locked', tmp_path)
    assert outcome.terminal_state == 'failed'
    assert '占用' in outcome.user_message
    assert_well_formed(outcome)


def test_page_changed_goes_manual_review(tmp_path):
    outcome = run('page_changed', tmp_path)
    assert outcome.terminal_state == 'manual_review'
    assert '页面' in outcome.user_message
    assert_well_formed(outcome)


def test_user_cancel_has_no_side_effects(tmp_path):
    outcome = run('user_cancel', tmp_path)
    assert outcome.terminal_state == 'cancelled'
    assert 'run_terminal' in outcome.evidence
    assert_well_formed(outcome)


def test_skill_conflict_rejected(tmp_path):
    outcome = run('skill_conflict', tmp_path)
    assert outcome.terminal_state == 'rejected'
    assert '冲突' in outcome.user_message
    assert_well_formed(outcome)


def test_corrupt_zip_rejected(tmp_path):
    outcome = run('corrupt_zip', tmp_path)
    assert outcome.terminal_state == 'rejected'
    assert '损坏' in outcome.user_message
    assert_well_formed(outcome)


def test_cancel_drill_uses_real_runtime_cancel(tmp_path):
    """取消演练必须真实经过 WorkflowRuntime 的 cancel 事件。"""
    from asset_based_agent.technical_platform import failure_drills
    calls = []

    original = failure_drills._drive_cancel
    def spy(tmp_path, *args, **kwargs):
        calls.append('driven')
        return original(tmp_path, *args, **kwargs)
    failure_drills._drive_cancel = spy
    try:
        outcome = run('user_cancel', tmp_path)
    finally:
        failure_drills._drive_cancel = original
    assert calls == ['driven']
    assert outcome.terminal_state == 'cancelled'
