"""Separate dialog for selecting files used by the next review round."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..domain.models import SourceFile


class ReplacementDialog(QDialog):
    def __init__(self, current_files: list[SourceFile], parent=None) -> None:
        super().__init__(parent)
        self.current_files = current_files
        self.pending_paths: list[Path] = []
        self.setWindowTitle("上传修改文件")
        self.setMinimumSize(820, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("上一轮文件会继续保留。请选择新文件及其替换对象。"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["新文件", "替换上一轮文件"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add_button = QPushButton("添加修改文件")
        remove_button = QPushButton("移除选中项")
        start_button = QPushButton("开启新一轮审核")
        cancel_button = QPushButton("取消")
        add_button.clicked.connect(self._add_files)
        remove_button.clicked.connect(self._remove_selected)
        start_button.clicked.connect(self._accept_if_valid)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        buttons.addWidget(start_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def selections(self) -> list[tuple[Path, str | None]]:
        values: list[tuple[Path, str | None]] = []
        for row, path in enumerate(self.pending_paths):
            combo = self.table.cellWidget(row, 1)
            combo = cast(QComboBox, combo)
            target = combo.currentData(Qt.ItemDataRole.UserRole)
            values.append((path, str(target) if target else None))
        return values

    def _add_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择修改文件",
            "",
            "审核文件 (*.docx *.xlsx *.xlsm *.pdf *.doc *.xls)",
        )
        for filename in filenames:
            path = Path(filename)
            if path in self.pending_paths:
                continue
            self.pending_paths.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(path.name))
            combo = QComboBox()
            combo.addItem("新增文件", None)
            for source in self.current_files:
                combo.addItem(source.original_name, source.file_id)
            suggested = self._suggest_target(path)
            if suggested:
                index = combo.findData(suggested, role=Qt.ItemDataRole.UserRole)
                combo.setCurrentIndex(max(index, 0))
            self.table.setCellWidget(row, 1, combo)

    def _suggest_target(self, path: Path) -> str | None:
        same_extension = [
            item
            for item in self.current_files
            if item.extension.lower() == path.suffix.lower()
        ]
        if len(same_extension) == 1:
            return same_extension[0].file_id
        return None

    def _remove_selected(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self.table.removeRow(row)
            self.pending_paths.pop(row)

    def _accept_if_valid(self) -> None:
        if not self.pending_paths:
            QMessageBox.information(self, "尚未选择文件", "请至少添加一个修改文件。")
            return
        self.accept()
