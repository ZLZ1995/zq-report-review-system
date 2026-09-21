"""Native user verification for read-only tasks, never a website write receipt."""
import json
import sqlite3
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from .browser_task_spec import BrowserTaskScope, browser_execution_goal
from .permissions import PermissionService
from .store import now


class ReadonlyReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    method: Literal['user_confirmed_readonly']
    task_id: str = Field(min_length=1, max_length=128)
    origin: str = Field(min_length=1, max_length=2048)
    page_version: int = Field(ge=0)
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    summary_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    goal_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed_at: str = Field(min_length=1, max_length=64)


def validate_readonly_receipt(value, snapshot, detail):
    receipt = ReadonlyReceipt.model_validate(value)
    scope = BrowserTaskScope.model_validate(snapshot['browser_scope'])
    if (not set(scope.actions) <= {'observe', 'navigate', 'scroll', 'wait'}
            or receipt.task_id != snapshot['task_id'] or receipt.origin not in scope.origins
            or receipt.evidence_sha256 != sha256(detail['evidence'].encode()).hexdigest()
            or receipt.summary_sha256 != sha256(detail['summary'].encode()).hexdigest()
            or receipt.goal_sha256 != sha256(browser_execution_goal(snapshot).encode()).hexdigest()):
        raise ValueError('Read-only verification receipt does not match task')
    return receipt.model_dump()


def verify_readonly_completion(host, detail, *, confirm, is_current=lambda: True):
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        return None
    runtime = host.runtime
    if runtime is None or not isinstance(detail, dict):
        return None
    snapshot = json.loads(host.store.run(host.run_id)['snapshot'])
    scope = BrowserTaskScope.model_validate(snapshot['browser_scope'])
    # Clicking, filling or account use may modify the website. They need an
    # independently validated business receipt, not this read-only attestation.
    if not set(scope.actions) <= {'observe', 'navigate', 'scroll', 'wait'}:
        return None
    evidence, summary = detail.get('evidence'), detail.get('summary')
    if (not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2000
            or not isinstance(summary, str) or not summary.strip() or len(summary) > 2000):
        return None
    digest = sha256(evidence.encode()).hexdigest()
    proof = runtime.completion_evidence
    if (not isinstance(proof, dict) or proof.get('evidence_sha256') != digest
            or proof.get('origin') not in scope.origins):
        return None

    def active():
        try:
            binding = runtime.lease.binding
            PermissionService(host.store).verify(host.run_id)
            return (not host.cancel.is_set() and is_current() is True
                    and binding.owner == host.store.owner and binding.task_id == host.run_id
                    and runtime.leases.valid(runtime.lease) and runtime.authorized() is True
                    and runtime.observer._epoch == proof['page_version'])
        except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error):
            return False

    def read_evidence():
        if not active():
            return False
        wait = QEventLoop()
        result = []
        closed = [False]
        def observed(value):
            if not closed[0]:
                result.append(value)
                wait.quit()
        expiry = QTimer()
        expiry.setSingleShot(True)
        expiry.timeout.connect(wait.quit)
        guard = QTimer()
        guard.timeout.connect(lambda: None if active() else wait.quit())
        expiry.start(3000)
        guard.start(100)
        try:
            runtime.observer.observe(runtime.lease, observed)
            if not result:
                wait.exec()
        finally:
            closed[0] = True
            expiry.stop()
            guard.stop()
        value = result[0] if result else None
        return (active() and value is not None and runtime.observer.matches(runtime.lease, value)
                and value.origin == proof['origin'] and value.page_version == proof['page_version']
                and evidence in value.text)

    if not read_evidence() or confirm(snapshot, detail, active) is not True or not read_evidence():
        return None
    return {'method': 'user_confirmed_readonly', 'task_id': host.run_id,
            'origin': proof['origin'], 'page_version': proof['page_version'],
            'evidence_sha256': digest, 'summary_sha256': sha256(summary.encode()).hexdigest(),
            'goal_sha256': sha256(browser_execution_goal(snapshot).encode()).hexdigest(),
            'confirmed_at': now()}


class CompletionDialog(QDialog):
    def __init__(self, snapshot, detail, parent=None):
        super().__init__(parent)
        self.setWindowTitle('核对只读查询结果')
        self.resize(760, 580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('查询目标、结果与网页依据')
        self.details.setPlainText('\n\n'.join([
            '此处仅确认只读查询结果，不证明网站写入成功，也不授权新操作。',
            '本轮完整目标：\n' + browser_execution_goal(snapshot),
            '待核对结果：\n' + detail['summary'],
            '最新网页引用（网页内容未经独立信任）：\n' + detail['evidence'],
            '请核对目标、对象及结论。无法确认时选择“暂不确认”。']))
        layout.addWidget(self.details)
        self.consent = QCheckBox('我已核对上述目标与依据，确认本次只读查询结果')
        layout.addWidget(self.consent)
        buttons = QDialogButtonBox()
        self.accept_button = buttons.addButton('确认查询结果', QDialogButtonBox.ButtonRole.AcceptRole)
        self.reject_button = buttons.addButton('暂不确认', QDialogButtonBox.ButtonRole.RejectRole)
        self.accept_button.setAutoDefault(False)
        self.accept_button.setEnabled(False)
        self.reject_button.setDefault(True)
        self.reject_button.setFocus()
        self.consent.toggled.connect(self.accept_button.setEnabled)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def confirm_readonly_result(parent, snapshot, detail, active):
    if not active():
        return False
    dialog = CompletionDialog(snapshot, detail, parent)
    guard = QTimer(dialog)
    guard.timeout.connect(lambda: None if active() else dialog.reject())
    expiry = QTimer(dialog)
    expiry.setSingleShot(True)
    expiry.timeout.connect(dialog.reject)
    guard.start(100)
    expiry.start(120000)
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted and dialog.consent.isChecked() and active()
    finally:
        guard.stop()
        expiry.stop()
        dialog.deleteLater()
