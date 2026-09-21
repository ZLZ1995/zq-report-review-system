# S13 Shadow Mode：新旧决策对比、副作用隔离、指标与门槛（先红后绿）。
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
    ToolDescriptor,
    ToolResult,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.shadow import (
    InMemoryDiagnostics,
    LegacyDecision,
    ShadowCase,
    ShadowRunner,
)


def text_script(text, usage=None):
    events = [ModelEvent('message_start', {}),
              ModelEvent('text_delta', {'text': text})]
    if usage:
        events.append(ModelEvent('usage', usage))
    events.append(ModelEvent('message_complete', {}))
    return events


def tool_call_script(name, arguments, call_id='c1'):
    return [ModelEvent('message_start', {}),
            ModelEvent('tool_call_complete',
                       {'id': call_id, 'name': name, 'arguments': arguments}),
            ModelEvent('message_complete', {})]


class SpyTool:
    """副作用工具探针：一旦被真实执行即记录。"""

    def __init__(self, name='generate_report', risk='local_create'):
        self.descriptor = ToolDescriptor(name=name, description='d',
                                         input_schema={}, risk=risk)
        self.executed = 0

    async def execute(self, context, arguments, cancel):
        self.executed += 1
        return ToolResult(status='succeeded', content='已生成')


class ReadonlyTool:
    def __init__(self, name='inspect_files'):
        self.descriptor = ToolDescriptor(name=name, description='d',
                                         input_schema={}, risk='local_readonly')
        self.executed = 0

    async def execute(self, context, arguments, cancel):
        self.executed += 1
        return ToolResult(status='succeeded', result={'files': ['a.xlsx']})


class StubLegacyRouter:
    def __init__(self, decisions):
        self.decisions = decisions  # text -> LegacyDecision
        self.calls = []

    def decide(self, case):
        self.calls.append(case.text)
        return self.decisions[case.text]


def make_runner(scripts, decisions, *, tools=None, diagnostics=None):
    repo = InMemorySessionRepo()
    models = iter([FakeModelPort(script) for script in scripts])
    runner = ShadowRunner(
        repo=repo,
        model_factory=lambda: next(models),
        tools=tools or [],
        legacy_router=StubLegacyRouter(decisions),
        diagnostics=diagnostics or InMemoryDiagnostics(),
    )
    return runner, repo


# ---------------------------------------------------------------- 基本对比

def test_chat_case_full_agreement_has_no_diff():
    runner, _ = make_runner(
        [[text_script('你好！有什么可以帮你？')]],
        {'你好': LegacyDecision(kind='chat', reply='你好！')})
    comparison = runner.run_case(ShadowCase(session_id='s1', text='你好',
                                            expected_kind='chat'))
    assert comparison.new.kind == 'chat'
    assert comparison.new.draft == '你好！有什么可以帮你？'
    assert comparison.diffs == ()


def test_shadow_run_does_not_touch_user_conversation():
    runner, repo = make_runner(
        [[text_script('草稿回复')]],
        {'问题': LegacyDecision(kind='chat', reply='旧回复')})
    repo.create_session('s1', project_id='p1', owner_id='u1', title='t')
    runner.run_case(ShadowCase(session_id='s1', text='问题'))
    # 用户会话主 lane 不得出现 shadow 内容
    assert repo.entries('s1', 'main') == []
    # 差异只进诊断
    assert len(runner.diagnostics.records) == 1
    assert runner.diagnostics.records[0].session_id == 's1'


def test_shadow_never_executes_side_effect_tools():
    spy = SpyTool()
    runner, _ = make_runner(
        [[tool_call_script('generate_report', {'file_ids': ['f1']}),
          text_script('报告已生成（草案）')]],
        {'生成报告': LegacyDecision(kind='skill', skill_id='generate_report',
                                    file_ids=('f1',))},
        tools=[spy])
    comparison = runner.run_case(ShadowCase(session_id='s1', text='生成报告',
                                            expected_kind='skill',
                                            expected_skill='generate_report',
                                            expected_files=('f1',)))
    assert spy.executed == 0  # 新系统不得执行副作用 Tool
    assert comparison.new.kind == 'skill'
    assert comparison.new.skill_id == 'generate_report'
    assert comparison.new.file_ids == ('f1',)
    assert comparison.diffs == ()


def test_readonly_tools_may_execute_in_shadow():
    readonly = ReadonlyTool()
    runner, _ = make_runner(
        [[tool_call_script('inspect_files', {}), text_script('项目里有 a.xlsx')]],
        {'看看文件': LegacyDecision(kind='chat', reply='项目里有 a.xlsx')},
        tools=[readonly])
    comparison = runner.run_case(ShadowCase(session_id='s1', text='看看文件'))
    assert readonly.executed == 1  # 只读工具允许真实执行
    assert comparison.new.kind == 'chat'


# ---------------------------------------------------------------- 差异与指标

def test_tool_selection_disagreement_is_recorded():
    runner, _ = make_runner(
        [[tool_call_script('generate_report', {}), text_script('草案')]],
        {'做表': LegacyDecision(kind='skill', skill_id='make_table')},
        tools=[SpyTool()])
    comparison = runner.run_case(ShadowCase(session_id='s1', text='做表'))
    assert 'skill_id' in comparison.diffs


def test_unnecessary_clarification_is_flagged():
    runner, _ = make_runner(
        [[text_script('请补充一下你想分析哪个文件？')]],
        {'分析一下': LegacyDecision(kind='chat', reply='直接回答了')})
    comparison = runner.run_case(ShadowCase(session_id='s1', text='分析一下'))
    assert comparison.new.kind == 'clarify'
    assert 'clarification' in comparison.diffs


def test_metrics_cover_required_dimensions():
    runner, _ = make_runner(
        [[text_script('好', usage={'input_tokens': 10, 'output_tokens': 5})],
         [tool_call_script('generate_report', {'file_ids': ['f1']}),
          text_script('草案', usage={'input_tokens': 20, 'output_tokens': 8})],
         [tool_call_script('generate_report', {'file_ids': ['f1']}, call_id='c2'),
          text_script('报告草案', usage={'input_tokens': 12, 'output_tokens': 6})],
         [text_script('请补充口径？')]],
        {'你好': LegacyDecision(kind='chat', reply='好'),
         '生成': LegacyDecision(kind='skill', skill_id='generate_report',
                                file_ids=('f1',)),
         '旧错新对': LegacyDecision(kind='chat', reply='错'),
         '新回归': LegacyDecision(kind='chat', reply='直接回答')},
        tools=[SpyTool()])
    cases = [
        ShadowCase(session_id='s1', text='你好', expected_kind='chat'),
        ShadowCase(session_id='s1', text='生成', expected_kind='skill',
                   expected_skill='generate_report', expected_files=('f1',)),
        ShadowCase(session_id='s1', text='旧错新对', expected_kind='skill',
                   expected_skill='generate_report', expected_files=('f1',)),
        ShadowCase(session_id='s1', text='新回归', expected_kind='chat'),
    ]
    metrics = runner.run(cases)
    assert metrics.total == 4
    assert metrics.chat_total == 2 and metrics.chat_success == 1
    assert metrics.skill_total >= 1 and metrics.skill_match >= 1
    assert metrics.file_scope_total == 2 and metrics.file_scope_match == 2
    assert metrics.unnecessary_clarifications == 1  # “新回归”案例
    assert metrics.legacy_wrong_new_right == 1
    assert metrics.new_regressions == 1
    assert metrics.model_calls >= 4
    assert metrics.input_tokens >= 42 and metrics.output_tokens >= 19
    assert metrics.avg_first_token_latency >= 0
    assert metrics.avg_duration > 0
    assert metrics.error_rate == 0


def test_failed_shadow_turn_counts_error():
    from asset_based_agent.technical_platform.agent_core.errors import (
        ModelProtocolError,
    )
    runner, _ = make_runner(
        [[ModelProtocolError('上游 500')], [text_script('好')]],
        {'问题': LegacyDecision(kind='chat', reply='旧回复'),
         '你好': LegacyDecision(kind='chat', reply='好')})
    comparison = runner.run_case(ShadowCase(session_id='s1', text='问题'))
    assert comparison.new.error
    metrics = runner.run([ShadowCase(session_id='s1', text='你好',
                                     expected_kind='chat')])
    assert metrics.error_rate > 0


def test_permission_consistency_checked_with_engine():
    runner, _ = make_runner(
        [[tool_call_script('generate_report', {}), text_script('草案')]],
        {'生成': LegacyDecision(kind='skill', skill_id='generate_report',
                                permission='ask')},
        tools=[SpyTool()])
    comparison = runner.run_case(ShadowCase(session_id='s1', text='生成'))
    # request 模式下 local_create 需询问，与旧系统一致
    assert 'permission' not in comparison.diffs
    runner2, _ = make_runner(
        [[tool_call_script('generate_report', {}), text_script('草案')]],
        {'生成': LegacyDecision(kind='skill', skill_id='generate_report',
                                permission='allow')},
        tools=[SpyTool()])
    comparison2 = runner2.run_case(ShadowCase(session_id='s1', text='生成'))
    assert 'permission' in comparison2.diffs


# ---------------------------------------------------------------- 门槛

def test_gates_pass_on_clean_dataset():
    runner, _ = make_runner(
        [[text_script('好')],
         [tool_call_script('generate_report', {'file_ids': ['f1']}),
          text_script('草案')]],
        {'你好': LegacyDecision(kind='chat', reply='好'),
         '生成': LegacyDecision(kind='skill', skill_id='generate_report',
                                file_ids=('f1',))},
        tools=[SpyTool()])
    metrics = runner.run([
        ShadowCase(session_id='s1', text='你好', expected_kind='chat'),
        ShadowCase(session_id='s1', text='生成', expected_kind='skill',
                   expected_skill='generate_report', expected_files=('f1',)),
    ])
    gates = metrics.evaluate_gates(legacy_clarification_rate=0.4)
    assert gates['chat_success'] is True
    assert gates['file_scope'] is True
    assert gates['no_side_effect_violation'] is True
    assert gates['no_cross_session_pollution'] is True
    assert gates['no_double_billing'] is True
    assert gates['skill_selection_accuracy'] is True
    assert gates['clarification_below_legacy'] is True
    assert gates['overall'] is True


def test_gates_fail_below_thresholds():
    runner, _ = make_runner(
        [[text_script('请补充？')]],
        {'你好': LegacyDecision(kind='chat', reply='直接答')})
    metrics = runner.run([ShadowCase(session_id='s1', text='你好',
                                     expected_kind='chat')])
    gates = metrics.evaluate_gates(legacy_clarification_rate=0.4)
    assert gates['chat_success'] is False  # 澄清不算普通聊天成功
    assert gates['clarification_below_legacy'] is False
    assert gates['overall'] is False


# ---------------------------------------------------------------- 安全

def test_no_cross_session_pollution_between_shadow_runs():
    runner, repo = make_runner(
        [[text_script('回答一')], [text_script('回答二')]],
        {'甲': LegacyDecision(kind='chat', reply='一'),
         '乙': LegacyDecision(kind='chat', reply='二')})
    runner.run_case(ShadowCase(session_id='sA', text='甲'))
    runner.run_case(ShadowCase(session_id='sB', text='乙'))
    # 各 shadow 会话只含自己的内容
    entries_a = repo.entries('sA__shadow', 'main')
    entries_b = repo.entries('sB__shadow', 'main')
    texts_a = [e.payload.get('text', '') for e in entries_a]
    texts_b = [e.payload.get('text', '') for e in entries_b]
    assert any('甲' in t for t in texts_a) and not any('乙' in t for t in texts_a)
    assert any('乙' in t for t in texts_b) and not any('甲' in t for t in texts_b)
    sessions = [r.session_id for r in runner.diagnostics.records]
    assert sessions == ['sA', 'sB']


def test_diagnostics_never_store_secrets():
    runner, _ = make_runner(
        [[text_script('好的')]],
        {'我的 password=pw123456 记一下': LegacyDecision(kind='chat', reply='好')})
    comparison = runner.run_case(
        ShadowCase(session_id='s1', text='我的 password=pw123456 记一下'))
    assert 'pw123456' not in str(runner.diagnostics.records[0].__dict__)
    assert 'pw123456' not in str(comparison.case.text)


def test_shadow_has_no_billing_channel():
    runner, _ = make_runner([[text_script('好')]],
                            {'你好': LegacyDecision(kind='chat', reply='好')})
    assert not hasattr(runner, 'billing')
    metrics = runner.run([ShadowCase(session_id='s1', text='你好')])
    assert metrics.charged_units == 0  # shadow 不触碰计费
