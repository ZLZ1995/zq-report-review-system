"""Query 对象：只读视图数据访问（View 不执行 SQL，只走 Query）。"""
from .view_models import SessionViewModel


class SessionListQuery:
    def __init__(self, repo, projector):
        self._repo = repo
        self._projector = projector

    def __call__(self):
        items = []
        for session in self._repo.list_sessions():
            vm = self._projector.session(session['id'])
            items.append(SessionViewModel(
                session_id=session['id'], title=session.get('title', ''),
                status=vm.status, unread=vm.unread))
        return items


class ConversationQuery:
    def __init__(self, projector):
        self._projector = projector

    def __call__(self, session_id, lane_id='main'):
        return self._projector.conversation(session_id, lane_id)
