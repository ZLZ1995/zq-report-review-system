"""Project/session navigation; refreshing it never selects a project database."""
import sqlite3

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from .navigation_snapshot import navigation_snapshot

ROLE = Qt.ItemDataRole.UserRole


class ProjectTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(16)
        self.setObjectName('projectTree')
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setColumnWidth(1, 28)
        self.setColumnWidth(2, 28)

    def refresh(self, store, manager, project_id, session_id, *, snapshot=None):
        roots = {self.topLevelItem(i).data(0, ROLE)[0]: self.topLevelItem(i)
                 for i in range(self.topLevelItemCount())}
        blocker = QSignalBlocker(self)
        seen = set()
        for project in navigation_snapshot(store) if snapshot is None else snapshot:
            identity = project['id']
            seen.add(identity)
            node = roots.get(identity)
            if node is None:
                node = QTreeWidgetItem(self, [project['name'], '✎', '⋯'])
                node.setData(0, ROLE, (identity, None))
                node.setExpanded(identity == project_id)
            try:
                if project.get('unavailable'):
                    raise ValueError('Project navigation temporarily unavailable')
                rows = project['sessions']
                node.setText(0, project['name'])
                node.setText(1, '✎')
                node.setText(2, '⋯')
                children = {node.child(i).data(0, ROLE)[1]: node.child(i) for i in range(node.childCount())}
                remaining = {row['id'] for row in rows}
                for row in rows:
                    child = children.get(row['id'])
                    if child is None:
                        child = QTreeWidgetItem(node)
                        child.setData(0, ROLE, (identity, row['id']))
                    labels = [row['title']]
                    if row['parent_session']:
                        labels.append('分支')
                        child.setToolTip(0, f"来源会话：{row['parent_session']}；消息：{row['fork_message']}")
                    if manager.for_session(store.owner, identity, row['id']) is not None:
                        labels.append('运行中')
                    if row['unread_count']:
                        labels.append(f"未读 {row['unread_count']}")
                    child.setText(0, ' · '.join(labels))
                    if (identity, row['id']) == (project_id, session_id):
                        self.setCurrentItem(child)
                for i in reversed(range(node.childCount())):
                    if node.child(i).data(0, ROLE)[1] not in remaining:
                        node.takeChild(i)
            except (OSError, ValueError, PermissionError, sqlite3.Error):
                node.setText(0, project['name'] + ' · 暂不可用')
                node.takeChildren()
        for i in reversed(range(self.topLevelItemCount())):
            if self.topLevelItem(i).data(0, ROLE)[0] not in seen:
                self.takeTopLevelItem(i)
        del blocker
