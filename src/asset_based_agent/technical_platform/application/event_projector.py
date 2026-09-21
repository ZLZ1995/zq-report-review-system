"""EventProjector：把 kernel 事件投影为 session-scoped ViewModel。

- 流式 delta 按 (session, lane, turn) 定向；
- 后台 Session 完成只更新对应 ViewModel 与未读数；
- 重启后 rebuild_all 从 Entry 重建全部状态；
- 状态按 Session 隔离，不存在全局 banner。
"""
from .view_models import ConversationViewModel, SessionViewModel

_TERMINAL_IDLE = {'operation_completed', 'operation_aborted',
                  'operation_unknown'}


class EventProjector:
    def __init__(self, repo):
        self._repo = repo  # 应用层组件（非 ViewModel），允许持有只读查询句柄
        self.sessions = {}
        self.conversations = {}
        self._active = None

    def __call__(self, event):
        session_vm = self.session(event.session_id)
        kind = event.event_type
        if kind == 'operation_started':
            session_vm.status = 'running'
        elif kind in _TERMINAL_IDLE or kind == 'operation_failed':
            session_vm.status = 'idle' if kind in _TERMINAL_IDLE else 'failed'
            if kind in ('operation_completed', 'operation_failed') \
                    and event.session_id != self._active:
                session_vm.unread += 1
            self.refresh(event.session_id, event.lane_id)
        elif kind == 'message_delta' and event.turn_id:
            self.conversation(event.session_id, event.lane_id).apply_delta(
                event.turn_id, event.payload.get('text', ''))
        elif kind == 'message_committed':
            if event.turn_id:
                self.conversation(event.session_id,
                                  event.lane_id).finalize_stream(event.turn_id)
            self.refresh(event.session_id, event.lane_id)
        elif kind in ('tool_completed', 'tool_failed'):
            self.refresh(event.session_id, event.lane_id)

    # ----------------------------------------------------------- accessors

    def session(self, session_id):
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionViewModel(session_id=session_id)
        return self.sessions[session_id]

    def conversation(self, session_id, lane_id='main'):
        key = (session_id, lane_id)
        if key not in self.conversations:
            self.conversations[key] = ConversationViewModel(session_id, lane_id)
            self.refresh(session_id, lane_id)
        return self.conversations[key]

    def refresh(self, session_id, lane_id):
        key = (session_id, lane_id)
        if key in self.conversations:
            self.conversations[key].rebuild(
                self._repo.entries(session_id, lane_id))

    def set_active(self, session_id):
        self._active = session_id
        self.session(session_id).unread = 0

    def status_for(self, session_id):
        return self.session(session_id).status

    def unread(self, session_id):
        return self.session(session_id).unread

    def rebuild_all(self):
        """UI 重启：从持久 Entry/operation 重建所有 ViewModel。"""
        for session in self._repo.list_sessions():
            vm = SessionViewModel(session_id=session['id'],
                                  title=session.get('title', ''))
            vm.status = ('running' if self._repo.open_operations(session['id'])
                         else 'idle')
            self.sessions[session['id']] = vm
