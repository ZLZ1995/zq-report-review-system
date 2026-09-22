"""Create or continue local review projects."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..branding import APPLICATION_NAME
from ..services.project_service import ProjectDeletionError, ProjectService


class ProjectWindow(QMainWindow):
    project_selected = Signal(object)
    logout_requested = Signal()

    def __init__(self, project_service: ProjectService, username: str, parent=None) -> None:
        super().__init__(parent)
        self.project_service = project_service
        self.username = username
        self.setWindowTitle(f"{APPLICATION_NAME} - 项目")
        self.setMinimumSize(760, 520)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        header = QHBoxLayout()
        header.addWidget(QLabel(f"当前用户：{self.username}"))
        header.addStretch(1)
        logout = QPushButton("退出登录")
        logout.clicked.connect(self.logout_requested.emit)
        header.addWidget(logout)
        layout.addLayout(header)

        layout.addWidget(QLabel("请选择继续已有项目，或创建新项目。"))
        self.project_list = QListWidget()
        self.project_list.itemDoubleClicked.connect(lambda _item: self._continue())
        self.project_list.currentItemChanged.connect(self._update_actions)
        layout.addWidget(self.project_list)

        buttons = QHBoxLayout()
        create_button = QPushButton("创建新项目")
        continue_button = QPushButton("继续项目")
        self.delete_button = QPushButton("删除项目")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        refresh_button = QPushButton("刷新")
        create_button.clicked.connect(self._create)
        continue_button.clicked.connect(self._continue)
        self.delete_button.clicked.connect(self._delete)
        refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(create_button)
        buttons.addWidget(continue_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.setCentralWidget(container)

    def refresh(self) -> None:
        from ..repositories.project_repository import CorruptedProjectEntry

        self.project_list.clear()
        for project in self.project_service.list_projects():
            if isinstance(project, CorruptedProjectEntry):
                # S5-03：损坏项目可见——显示"项目损坏/不可访问"，而不是消失
                item = QListWidgetItem(
                    f"〈项目损坏/不可访问〉 {project.name}    "
                    f"原因：{project.error}    "
                    f"最后更新：{project.updated_at.strftime('%Y-%m-%d %H:%M')}"
                )
                item.setData(Qt.ItemDataRole.UserRole, None)
            else:
                item = QListWidgetItem(
                    f"{project.name}    状态：{project.status.value}    "
                    f"最后更新：{project.updated_at.astimezone().strftime('%Y-%m-%d %H:%M')}"
                )
                item.setData(Qt.ItemDataRole.UserRole, project.project_id)
            self.project_list.addItem(item)
        self._update_actions()

    def _update_actions(self, *_args) -> None:
        self.delete_button.setEnabled(self.project_list.currentItem() is not None)

    def _create(self) -> None:
        name, accepted = QInputDialog.getText(self, "创建新项目", "项目名称")
        if not accepted:
            return
        try:
            project = self.project_service.create_project(name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法创建项目", str(exc))
            return
        self.project_selected.emit(project)

    def _continue(self) -> None:
        item = self.project_list.currentItem()
        if item is None:
            QMessageBox.information(self, "请选择项目", "请先选择一个历史项目。")
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id is None:
            QMessageBox.warning(
                self, "项目损坏", "该项目清单已损坏，无法继续；请修复或删除项目目录。")
            return
        project = self.project_service.continue_project(str(project_id))
        self.project_selected.emit(project)

    def _delete(self) -> None:
        item = self.project_list.currentItem()
        if item is None:
            QMessageBox.information(self, "请选择项目", "请先选择要删除的项目。")
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id is None:
            QMessageBox.warning(
                self, "项目损坏",
                "该项目清单已损坏，无法在此删除；请检查项目目录后手动处理。")
            return
        project = self.project_service.continue_project(str(project_id))
        answer = QMessageBox.question(
            self,
            "确认删除项目",
            (
                f"确定永久删除项目“{project.name}”吗？\n\n"
                "项目目录中的上传副本、审核记录和项目内报告将被删除。"
                "上传前的原始文件不会被删除。\n\n"
                "此操作无法撤销。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project_service.delete_project(project_id)
        except (ProjectDeletionError, FileNotFoundError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法删除项目", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "删除成功", f"项目“{project.name}”已删除。")
