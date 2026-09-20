"""K05：平台状态查询返回确定性数据；文件只读问答只用本轮明确指向的文件。

平台查询的意图仍由结构化模型判断（间谍客户端先返回 consult 裁决），
回答数据必须来自本地数据库/注册表，不得由模型编造；文件问答只读取
本轮明确选择或明确提及的文件，只发送可见内容的受限摘要，绝不写回原件。
"""


from test_consultation_routing import SpyClient, consult_response, make_store


def add_named_file(store, project, tmp_path, name, header):
    from openpyxl import Workbook

    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / name
    wb = Workbook()
    wb.active['A1'] = header
    wb.save(path)
    wb.close()
    return store.add_file(project, path, digest(path))


def scripted_spy(*replies):
    """每次 understand 调用依次返回脚本化的咨询裁决。"""
    spy = SpyClient()
    calls = {'index': 0}
    def understand(payload, *, cancel=None):
        spy.understand_calls.append(payload)
        text = replies[min(calls['index'], len(replies) - 1)]
        calls['index'] += 1
        return consult_response(payload, text)
    spy.understand_task = understand
    return spy


def load_router():
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    return TurnRouter


def conversation_state(store, session):
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    return ConversationState(store).read(session)


# ------------------------------------------------------------------ 平台查询

def test_file_count_query_answers_from_database_not_model(tmp_path):
    """“当前项目有几个文件”：回答与数据库一致，模型编造的数字被真实数据替换。"""
    store, project, session = make_store(tmp_path)
    add_named_file(store, project, tmp_path, '资料A.xlsx', '表头A')
    add_named_file(store, project, tmp_path, '资料B.xlsx', '表头B')
    spy = scripted_spy('项目里应该有 5 个文件吧。')
    outcome = load_router()(store, spy).submit(
        session, '当前项目有几个文件？', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    assert '2 个文件' in outcome.reply and '资料A.xlsx' in outcome.reply
    assert '5 个文件' not in outcome.reply
    assert len(spy.understand_calls) == 1
    assert conversation_state(store, session)['task_id'] is None


def test_skill_query_lists_installed_and_builtin(tmp_path):
    store, _project, session = make_store(tmp_path)
    from asset_based_agent.technical_platform.skill_installation import (
        SkillInstallation,
    )
    SkillInstallation(store)  # 确保 installed_skills 表已建立
    with store.connect() as db:
        db.execute(
            'INSERT INTO installed_skills (owner,skill_id,version,name,sha256,package,enabled,created)'
            " VALUES ('alice','custom.skill','1.2.0','自定义技能','x',x'00',1,'2026-09-20')")
    spy = scripted_spy('你安装了很多技能。')
    outcome = load_router()(store, spy).submit(
        session, '我安装了哪些Skill？', model_id='m', selected_ids=[])
    assert '自定义技能 1.2.0（启用）' in outcome.reply
    assert '评估报告审核' in outcome.reply  # 内置能力一并列出
    assert conversation_state(store, session)['task_id'] is None


def test_task_status_query_reflects_conversation_state(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy = scripted_spy('任务进行中。')
    router = load_router()(store, spy)
    outcome = router.submit(session, '上一个任务完成了吗？', model_id='m', selected_ids=[])
    assert '没有' in outcome.reply
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    state = ConversationState(store)
    state.start(session, expected_revision=state.read(session)['revision'])
    spy2 = scripted_spy('都完成了。')
    outcome = load_router()(store, spy2).submit(
        session, '现在任务状态如何？', model_id='m', selected_ids=[])
    assert '尚未开始执行' in outcome.reply


def test_version_query_reports_client_and_server_build(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy = scripted_spy('版本是最新的。')
    spy.server_build_info = lambda: {
        'build_sha': '52eed3496e06f7b6d49a0028aa51e3b8797679fd', 'schema_version': 1}
    outcome = load_router()(store, spy).submit(
        session, '现在客户端和服务端版本是多少？', model_id='m', selected_ids=[])
    from asset_based_agent.technical_platform.release_info import CLIENT_VERSION
    assert f'客户端 {CLIENT_VERSION}' in outcome.reply
    assert '52eed3496e06' in outcome.reply


def test_project_list_query_answers_from_database(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy = scripted_spy('有很多项目。')
    outcome = load_router()(store, spy).submit(
        session, '我有哪些项目？', model_id='m', selected_ids=[])
    assert '1 个项目：one' in outcome.reply


# ------------------------------------------------------------------ 文件只读问答

def test_file_qa_grounded_on_visible_summary_with_audit(tmp_path):
    """提及文件名的咨询：第二次轻量调用只带可见摘要；答复落地并留审计事件。"""
    store, project, session = make_store(tmp_path)
    add_named_file(store, project, tmp_path, '资料.xlsx', '合成表头')
    spy = scripted_spy('我看不到文件内容。', '表里有合成表头。')
    outcome = load_router()(store, spy).submit(
        session, '资料.xlsx里有什么内容？', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    assert outcome.reply == '表里有合成表头。'
    assert len(spy.understand_calls) == 2
    grounded = spy.understand_calls[1]
    assert '合成表头' in grounded['prompt']
    assert '只读可见摘要' in grounded['prompt']
    assert str(tmp_path) not in str(grounded), '文件问答不得发送绝对路径'
    assert grounded['skills'] == []
    roles = [(m['role'], m['text']) for m in store.messages(session)]
    assert any(role == 'event' and '只读' in text and '资料.xlsx' in text
               for role, text in roles), '文件只读问答必须留下可审计事件'
    assert conversation_state(store, session)['task_id'] is None


def test_file_qa_deictic_reference_uses_selected_files(tmp_path):
    """“这份表”类指代：只对本轮已选文件取可见摘要。"""
    store, project, session = make_store(tmp_path)
    file_id = add_named_file(store, project, tmp_path, '资料.xlsx', '合成表头')
    spy = scripted_spy('看不到。', '报告期在表头附近。')
    outcome = load_router()(store, spy).submit(
        session, '这份表的报告期是什么？', model_id='m', selected_ids=[file_id])
    assert outcome.reply == '报告期在表头附近。'
    assert len(spy.understand_calls) == 2
    assert '合成表头' in spy.understand_calls[1]['prompt']


def test_file_qa_never_reads_unmentioned_history(tmp_path):
    """未被选择也未被提及的历史附件不得进入文件问答。"""
    store, project, session = make_store(tmp_path)
    add_named_file(store, project, tmp_path, '资料A.xlsx', '合成表头A')
    add_named_file(store, project, tmp_path, '旧底稿.xlsx', '机密历史表头')
    spy = scripted_spy('看不到。', 'A 表里有合成表头A。')
    outcome = load_router()(store, spy).submit(
        session, '资料A.xlsx里有什么内容？', model_id='m', selected_ids=[])
    assert outcome.reply == 'A 表里有合成表头A。'
    assert len(spy.understand_calls) == 2
    grounded = spy.understand_calls[1]
    assert '合成表头A' in grounded['prompt']
    assert '机密历史表头' not in str(grounded), '历史附件不得串入本轮文件问答'


def test_consult_without_file_pointer_stays_single_call(tmp_path):
    """未指向文件的普通咨询：不触发文件落地，仍只有一次轻量调用。"""
    store, project, session = make_store(tmp_path)
    add_named_file(store, project, tmp_path, '资料.xlsx', '合成表头')
    spy = scripted_spy('通常包括声明、摘要、正文与附件。')
    outcome = load_router()(store, spy).submit(
        session, '评估报告一般包括哪些部分？', model_id='m', selected_ids=[])
    assert outcome.reply == '通常包括声明、摘要、正文与附件。'
    assert len(spy.understand_calls) == 1
    assert '合成表头' not in str(spy.understand_calls), '普通咨询不得夹带文件内容'
