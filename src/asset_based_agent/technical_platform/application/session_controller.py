"""SessionController：会话列表、打开、切换、草稿与权限模式。

打开 Session 是只读重建，绝不写 Entry；草稿是 session-scoped UI 态。
"""
from .commands import (
    CreateSession,
    OpenSession,
    SaveDraft,
    SetPermissionMode,
    SwitchSession,
)


class SessionController:
    def __init__(self, repo, projector):
        self._repo = repo
        self._projector = projector
        self._drafts = {}

    def register(self, bus):
        bus.register(OpenSession, self.open_session)
        bus.register(SwitchSession, self.switch_session)
        bus.register(SaveDraft, self.save_draft)
        bus.register(SetPermissionMode, self.set_permission_mode)
        bus.register(CreateSession, self.create_session)

    def open_session(self, command):
        self._projector.session(command.session_id)
        return self._projector.conversation(command.session_id, 'main')

    def switch_session(self, command):
        self._projector.set_active(command.session_id)
        return {'active': command.session_id}

    def save_draft(self, command):
        self._drafts[command.session_id] = command.text
        return {'saved': True}

    def draft(self, session_id):
        return self._drafts.get(session_id, '')

    def set_permission_mode(self, command):
        self._repo.set_permission_mode(command.session_id, command.mode)
        return {'mode': command.mode}

    def create_session(self, command):
        self._repo.create_session(command.session_id,
                                  project_id=command.project_id,
                                  owner_id=command.owner_id,
                                  title=command.title)
        return {'session_id': command.session_id}

    def list_sessions(self):
        return self._repo.list_sessions()
