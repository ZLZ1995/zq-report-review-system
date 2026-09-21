# 回归：勾选文件必须进入新 Agent 管线的 operation 绑定与模型上下文。
#
# 事故：生产客户端走 _try_agent_submit → AgentGateway.submit → AgentKernel，
# 全程只传文本，UI 勾选的项目文件从未写入 turn_file_bindings，
# ContextBuilder 渲染“本轮文件摘要：无”，模型只能回答“没有收到文件”。
from hashlib import sha256

import pytest

from asset_based_agent.technical_platform.agent_core.context_builder import (
    ContextBuilder,
)
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
)
from asset_based_agent.technical_platform.agent_core.errors import (
    InvalidRequest,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
from asset_based_agent.technical_platform.agent_gateway import AgentGateway
from asset_based_agent.technical_platform.flags import FeatureFlagStore
from asset_based_agent.technical_platform.store import PlatformStore


def text_script(text):
    return [ModelEvent('message_start', {}),
            ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def make_stack(tmp_path, *, scripts=()):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    flags.set_enabled('chat', True)
    models = iter(FakeModelPort(list(group)) for group in scripts)
    gateway = AgentGateway(
        store, session, flags=flags,
        model_port_factory=lambda: next(models),
        permission_mode_getter=lambda: 'risk',
    )
    return store, project, session, gateway


def add_file(store, project, tmp_path, name):
    path = tmp_path / name
    path.write_bytes(name.encode('utf-8'))
    return store.add_file(project, path, digest(path))


# ---------------------------------------------------------------- 网关绑定

def test_checked_files_bound_as_explicit_selection(tmp_path):
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('收到文件')]])
    file_id = add_file(store, project, tmp_path, 'A8T-PL202607.xlsx')
    result = gateway.submit('根据上传的文件生成评估明细表', file_ids=[file_id])
    assert result['status'] == 'completed'
    operations = gateway.repo.open_operations(session)
    assert operations == []
    bindings = gateway.repo.operation_files(
        gateway.repo.entries(session, 'main')[-1].operation_id)
    assert len(bindings) == 1
    assert bindings[0]['file_id'] == file_id
    assert bindings[0]['binding_kind'] == 'explicit_selection'
    assert bindings[0]['sha256'] == digest(tmp_path / 'A8T-PL202607.xlsx')
    # legacy files 表在同库：绑定记录应带出文件名
    assert bindings[0]['name'] == 'A8T-PL202607.xlsx'


def test_unknown_file_id_rejected_before_any_operation(tmp_path):
    _, _, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('不应到达')]])
    with pytest.raises(ValueError):
        gateway.submit('用文件生成表', file_ids=['不存在的id'])
    assert gateway.repo.entries(session, 'main') == []


def test_duplicate_file_ids_rejected(tmp_path):
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('不应到达')]])
    file_id = add_file(store, project, tmp_path, '资料.xlsx')
    with pytest.raises(ValueError):
        gateway.submit('用文件生成表', file_ids=[file_id, file_id])
    assert gateway.repo.entries(session, 'main') == []


def test_context_builder_shows_file_name_in_turn_section(tmp_path):
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('好')]])
    file_id = add_file(store, project, tmp_path, '2026.07_TB.xlsx')
    gateway.submit('看看这份表', file_ids=[file_id])
    operation_id = gateway.repo.entries(session, 'main')[-1].operation_id
    operation = gateway.repo.get_operation(operation_id)
    built = ContextBuilder().build(repo=gateway.repo, operation=operation)
    sections = [m['payload']['text'] for m in built.messages
                if m['role'] == 'system']
    file_section = next(text for text in sections if '本轮文件摘要' in text)
    assert '2026.07_TB.xlsx(explicit_selection)' in file_section


def test_submit_without_files_keeps_empty_scope(tmp_path):
    _, _, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('好')]])
    gateway.submit('纯聊天')
    operation_id = gateway.repo.entries(session, 'main')[-1].operation_id
    assert gateway.repo.operation_files(operation_id) == []


# ---------------------------------------------------------------- 内核绑定校验

def test_kernel_binds_files_before_loop(tmp_path):
    import asyncio

    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    kernel = AgentKernel(repo=repo, model=FakeModelPort([text_script('好')]))
    accepted = asyncio.run(kernel.submit('s1', 'main', {
        'text': '用文件',
        'file_bindings': [{'file_id': 'f1', 'sha256': 'a' * 64}],
    }))
    bindings = repo.operation_files(accepted.operation_id)
    assert [(b['file_id'], b['binding_kind']) for b in bindings] == [
        ('f1', 'explicit_selection')]


def test_kernel_rejects_binding_without_sha256():
    import asyncio

    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    kernel = AgentKernel(repo=repo, model=FakeModelPort([text_script('好')]))
    with pytest.raises(InvalidRequest):
        asyncio.run(kernel.submit('s1', 'main', {
            'text': '用文件', 'file_bindings': [{'file_id': 'f1'}]}))


# ---------------------------------------------------------------- UI 接线透传

def test_checked_files_flow_from_ui_to_gateway(tmp_path):
    """app.submit() 必须把本轮勾选文件传给 AgentGateway.submit(file_ids=...)。"""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    import time

    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.app import PlatformWindow

    class RecordingGateway:
        new_path_available = True

        def __init__(self):
            self.received = None

        def submit(self, text, *, file_ids=(), on_event=None):
            self.received = {'text': text, 'file_ids': tuple(file_ids)}
            return {'status': 'completed', 'reply': '好', 'error_code': ''}

    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'ui.sqlite', 'tester')
    project = store.create_project('接线项目')
    store.create_session(project, '接线会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    file_id = add_file(store, project, tmp_path, 'A8T-BS202607.xlsx')
    window.refresh_details(selected_ids={file_id})
    assert window.selected_file_ids() == {file_id}

    gateway = RecordingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('根据上传的文件生成评估明细表')
    window.submit()
    deadline = time.perf_counter() + 10
    while window._agent_worker is not None and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert gateway.received is not None
    assert gateway.received['text'] == '根据上传的文件生成评估明细表'
    assert gateway.received['file_ids'] == (file_id,)
    window.close()


# ---------------------------------------------------------------- 本轮上传与历史资料策略

def test_new_uploads_bound_as_explicit_upload_regardless_of_selection(tmp_path):
    """本轮上传必须进上下文：即使未勾选也按 explicit_upload 绑定。"""
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('好')]])
    file_id = add_file(store, project, tmp_path, 'A8T-CF202607.xlsx')
    result = gateway.submit('根据上传的文件生成评估明细表', upload_ids=[file_id])
    assert result['status'] == 'completed'
    operation_id = gateway.repo.entries(session, 'main')[-1].operation_id
    bindings = gateway.repo.operation_files(operation_id)
    assert [(b['file_id'], b['binding_kind']) for b in bindings] == [
        (file_id, 'explicit_upload')]


def test_overlap_between_upload_and_selection_prefers_upload(tmp_path):
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('好')]])
    file_id = add_file(store, project, tmp_path, '重叠.xlsx')
    gateway.submit('用这个', file_ids=[file_id], upload_ids=[file_id])
    operation_id = gateway.repo.entries(session, 'main')[-1].operation_id
    bindings = gateway.repo.operation_files(operation_id)
    assert [(b['file_id'], b['binding_kind']) for b in bindings] == [
        (file_id, 'explicit_upload')]


def test_historical_files_discoverable_but_not_in_scope(tmp_path):
    """历史资料不进本轮文件摘要，但以清单形式对 Agent 可发现。"""
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('好')]])
    current = add_file(store, project, tmp_path, '本轮.xlsx')
    add_file(store, project, tmp_path, '去年历史.xlsx')
    gateway.submit('处理本轮文件', file_ids=[current])
    operation_id = gateway.repo.entries(session, 'main')[-1].operation_id
    operation = gateway.repo.get_operation(operation_id)
    built = ContextBuilder().build(repo=gateway.repo, operation=operation)
    sections = [m['payload']['text'] for m in built.messages
                if m['role'] == 'system']
    scope = next(text for text in sections if '本轮文件摘要' in text)
    assert '本轮.xlsx' in scope and '去年历史.xlsx' not in scope
    history = next(text for text in sections if '【项目历史资料】' in text)
    assert '去年历史.xlsx' in history and '本轮.xlsx' not in history
    rules = next(text for text in sections if '【Agent 行为规则】' in text)
    assert '历史资料' in rules and '工具' in rules


def test_no_history_section_when_project_has_only_bound_files(tmp_path):
    store, project, session, gateway = make_stack(
        tmp_path, scripts=[[text_script('好')]])
    current = add_file(store, project, tmp_path, '唯一.xlsx')
    gateway.submit('处理', file_ids=[current])
    operation_id = gateway.repo.entries(session, 'main')[-1].operation_id
    operation = gateway.repo.get_operation(operation_id)
    built = ContextBuilder().build(repo=gateway.repo, operation=operation)
    sections = [m['payload']['text'] for m in built.messages
                if m['role'] == 'system']
    assert not any('【项目历史资料】' in text for text in sections)


def test_reference_resolver_picks_up_new_uploads():
    """“新上传的N个文件”指代必须能落到 explicit_upload 绑定上。"""
    from asset_based_agent.technical_platform.agent_core.reference_resolver import (
        resolve_references,
    )
    bindings = [
        {'file_id': 'old', 'binding_kind': 'explicit_selection'},
        {'file_id': 'up1', 'binding_kind': 'explicit_upload'},
        {'file_id': 'up2', 'binding_kind': 'explicit_upload'},
    ]
    outcome = resolve_references(
        '把新上传的两个文件合并成一张表', bindings=bindings, entries=[])
    assert outcome['file_ids'] == ['up1', 'up2']


def test_ui_import_then_submit_sends_upload_ids(tmp_path):
    """UI 导入文件后发送：文件必须按 upload_ids 传给网关（与勾选无关）。"""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    import time

    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.app import PlatformWindow

    class RecordingGateway:
        new_path_available = True

        def __init__(self):
            self.received = None

        def submit(self, text, *, file_ids=(), upload_ids=(), on_event=None):
            self.received = {'text': text, 'file_ids': tuple(file_ids),
                             'upload_ids': tuple(upload_ids)}
            return {'status': 'completed', 'reply': '好', 'error_code': ''}

    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'ui2.sqlite', 'tester')
    project = store.create_project('接线项目')
    store.create_session(project, '接线会话')
    window = PlatformWindow(store)
    window.reload_projects(project)

    source = tmp_path / 'A8T-PL202607.xlsx'
    source.write_bytes(b'upload-bytes')
    window.import_files([str(source)])
    file_id = next(f['id'] for f in store.files(project)
                   if f['name'] == 'A8T-PL202607.xlsx')

    gateway = RecordingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('根据上传的文件生成评估明细表')
    window.submit()
    deadline = time.perf_counter() + 10
    while window._agent_worker is not None and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert gateway.received is not None
    assert gateway.received['upload_ids'] == (file_id,)
    assert gateway.received['file_ids'] == ()
    # 发送后本轮上传标记已清空，下一轮不会重复带入
    assert getattr(window, '_pending_upload_ids', set()) == set()
    window.close()
