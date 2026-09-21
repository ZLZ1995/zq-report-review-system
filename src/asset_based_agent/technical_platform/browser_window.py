"""Native message-to-browser handoff; no model-created execution authority."""
import sqlite3

from .agent_permission_modes import requires_browser_confirmation
from .browser_action_prompt import BrowserActionPrompt
from .browser_completion import confirm_readonly_result, verify_readonly_completion
from .browser_download_completion_ui import (
    confirm_download_result,
    verify_download_completion,
)
from .browser_login_prompt import select_login_account
from .browser_runtime_factory import create_browser_runtime
from .browser_task_host import BrowserTaskHost
from .browser_task_spec import build_understood_browser_task
from .browser_upload_prompt import confirm_upload
from .browser_upload_selection import select_upload_artifacts
from .conversation_state import ConversationState
from .permissions import PermissionService
from .project_catalog import ProjectCatalog


def start_browser_task(window, pending, understanding):
    store = window.store.active if isinstance(window.store, ProjectCatalog) else window.store
    client = window.client
    run_id = None
    if store is None or client is None:
        window.status.setText('请先选择项目并连接模型服务。')
        return

    def current():
        active = window.store.active if isinstance(window.store, ProjectCatalog) else window.store
        if (active is not store or store is None or window.client is not client
                or window.store.owner != pending.owner or window.project_id != pending.project_id
                or window.session_id != pending.session_id
                or window.model_combo.currentData() != pending.request.model_id):
            return False
        state = ConversationState(store).read(pending.session_id)
        return (state['task_id'] == pending.task_id and state['revision'] == pending.revision + 1
                and state['cancelled'])

    try:
        if window.worker or not current():
            raise ValueError('Stale browser proposal')
        snapshot = build_understood_browser_task(store, pending.session_id, pending.request,
                                                understanding, environment='production').to_snapshot()
        snapshot['permission_mode'] = window.agent_permission_mode()
        snapshot['conversation_handoff'] = {
            'task_id': pending.task_id, 'revision': pending.revision + 1,
            'request': pending.request.model_dump(),
        }
        upload_artifacts = []
        if 'upload' in snapshot['browser_scope']['actions']:
            upload_artifacts = select_upload_artifacts(window, store, pending.session_id, current)
            if not upload_artifacts:
                window.status.setText('未选择本次上传成果，浏览器任务已取消。')
                return
            if not current():
                raise ValueError('Upload selection context changed')
            snapshot['upload_artifacts'] = upload_artifacts
        if not window.confirm_compound_plan(snapshot):
            window.status.setText('已取消浏览器任务，未访问网站。')
            return
        if not current():
            raise ValueError('Browser context changed during confirmation')
        if window.browser_panel is None:
            window.toggle_browser()
        if not current() or window.browser_panel is None:
            raise ValueError('Browser is unavailable')
        panel = window.browser_panel
        if panel.session.owner != pending.owner or panel.tabs.count() >= 12:
            raise ValueError('Browser owner changed or tab limit reached')
        view = panel.new_tab(blank=False)
        page = view.page()
        window.details.show()
        window.details.setCurrentWidget(panel)
        run_id = store.start_run(pending.session_id, snapshot)
        PermissionService(store).authorize(run_id, snapshot, confirmed=True)
    except (ValueError, OSError, RuntimeError, sqlite3.Error):
        if run_id is not None:
            store.transition(run_id, 'failed', '浏览器授权保存失败，未执行')
        window.status.setText('浏览器任务范围或环境已变化，未执行；请核对当前项目、模型与数据目录。')
        return

    def factory(host):
        def active(request):
            runtime = host.runtime
            if (runtime is None or window.store.owner != pending.owner
                    or not panel.task_leases.valid(runtime.lease)
                    or request.tab_id != runtime.lease.tab_id
                    or request.page_version != runtime.observer._epoch):
                return False
            try:
                with store.connect() as db:
                    PermissionService(store)._browser_binding(db, request)
                return True
            except (ValueError, OSError, RuntimeError, sqlite3.Error):
                return False
        prompt = BrowserActionPrompt(window, is_active=active,
                                     permission_mode=window.agent_permission_mode)
        host.finished.connect(prompt.close)
        host.finished.connect(prompt.deleteLater)
        return create_browser_runtime(host, client, panel.task_leases, page, confirmed=True,
            confirm_action=prompt, confirm_navigation=prompt.navigate, downloads=panel.downloads.controller,
            upload_artifacts=upload_artifacts,
            confirm_upload=(lambda observation, proposal, artifact, allowed:
                (confirm_upload(window, observation, proposal, artifact,
                                lambda: current() and allowed())
                 if requires_browser_confirmation(window.agent_permission_mode(), 'upload')
                 else current() and allowed())) if upload_artifacts else None,
            select_account=lambda origin, accounts, allowed: select_login_account(
                window, origin, accounts, lambda: current() and allowed()))

    window.run_id = run_id
    upload_note = (f'仅允许本次选定的{len(upload_artifacts)}个成果副本，上传前再次确认网站与业务对象；不上传原始资料。'
                   if upload_artifacts else '不上传本地文件。')
    store.append(pending.session_id, 'event', '浏览器计划：确认范围 → 专属标签页 → 逐步操作与核验；' + upload_note)
    window.render_messages()
    def verify(detail):
        if 'download' in snapshot['browser_scope']['actions']:
            return verify_download_completion(host, detail, is_current=current,
                confirm=lambda task, result, active:
                (confirm_download_result(window, task, result, active)
                 if requires_browser_confirmation(window.agent_permission_mode(), 'download')
                 else active()))
        return verify_readonly_completion(host, detail, is_current=current,
            confirm=lambda snapshot, result, active: confirm_readonly_result(window, snapshot, result, active))
    host = window.register_task_worker(BrowserTaskHost(store, run_id, window, runtime_factory=factory,
                                                     verify_completion=verify))
    window.set_busy(True)
    host.start()
