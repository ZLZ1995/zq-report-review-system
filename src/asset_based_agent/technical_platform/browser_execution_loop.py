"""GUI-thread browser loop with network-only workers and no automatic write replay.

The host supplies an already claimed task/tab, receipt-backed browser adapters
and a live durable-authorization check. A completion proposal is surfaced for
business verification, never silently converted to a succeeded task.
"""
import sqlite3
import time
from hashlib import sha256
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot

from ..agent_contracts import BrowserIntent
from ..browser_contracts import (
    BrowserStepProposal,
    BrowserStepRequest,
    DownloadSummary,
    validate_browser_step,
)
from ..report_review_app.services.resource_locks import CLIENT_RESOURCES
from .browser_download_worker import DownloadVerificationWorker


class BrowserProposalWorker(QThread):
    def __init__(self, client, request, cancel, parent):
        super().__init__(parent)
        self.client, self.request, self.cancel = client, request, cancel
        self.result = None
        self.error = False

    def run(self):
        try:
            with CLIENT_RESOURCES.lease(('model',), self.cancel):
                if not self.cancel.is_set():
                    self.result = self.client.propose_browser_step(self.request.model_dump(), cancel=self.cancel)
        except Exception:  # noqa: BLE001 - never expose transport/credential exception text
            self.error = True


class BrowserExecutionLoop(QObject):
    progress = Signal(str)
    finished = Signal(str, object)

    def __init__(self, client, observer, navigation, leases, lease, *, task_id, model_id,
                 goal, scope, authorized, parent=None, login=None, downloads=None, uploads=None):
        super().__init__(parent)
        if task_id != lease.binding.task_id:
            raise PermissionError('Browser loop task mismatch')
        self.client, self.observer, self.navigation = client, observer, navigation
        self.leases, self.lease = leases, lease
        self.task_id, self.model_id, self.goal = task_id, model_id, goal
        self.scope = BrowserIntent.model_validate(scope.model_dump())
        self.authorized = authorized
        self.login = login
        self.downloads = downloads
        self.uploads = uploads
        self.download_results = []
        self.cancel = lease.worker.cancel
        self._running, self._started = False, False
        self._terminal = None
        self._worker = None
        self._verification_worker = None
        self._sequence = 0
        self._deadline = 0.0
        self._generation = 0
        self.completion_evidence = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def isRunning(self):
        return (self._running or (self._worker is not None and self._worker.isRunning())
                or (self._verification_worker is not None and self._verification_worker.isRunning())
                or (self.uploads is not None and self.uploads.isRunning()))

    def _active(self):
        try:
            return (self._running and self._terminal is None and not self.cancel.is_set()
                    and self.leases.valid(self.lease) and self.authorized() is True)
        except (ValueError, TypeError, OSError, RuntimeError):
            return False

    def start(self):
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread() or self._started:
            raise RuntimeError('Browser loop must start once on the GUI thread')
        self._started = self._running = True
        self.timer.start()
        self._observe(initial=True)

    def stop(self):
        self.cancel.set()
        self._finish('cancelled')

    def _tick(self):
        if not self._active():
            self._finish('cancelled')
        elif self._deadline and time.monotonic() > self._deadline:
            self._finish('unknown')

    def _observe(self, *, initial=False):
        if not self._active():
            self._finish('cancelled')
            return
        if 'observe' not in self.scope.actions:
            self._finish('needs_input', {'reason':'observation_not_in_scope'})
            return
        self._deadline = time.monotonic() + 45
        self._generation += 1
        generation = self._generation
        self.progress.emit('正在读取本任务网页的可见内容')
        def observed(value):
            if generation != self._generation or not self._active():
                return
            if value is None and not initial:
                self._finish('unknown')
                return
            self._propose(value)
        self.observer.observe(self.lease, observed)

    def _propose(self, observation):
        if not self._active():
            self._finish('cancelled')
            return
        if self._sequence >= 32:
            self._finish('needs_input', {'reason':'step_limit'})
            return
        self._sequence += 1
        try:
            request = BrowserStepRequest(request_id=uuid4().hex, model_id=self.model_id,
                task_id=self.task_id, sequence=self._sequence, goal=self.goal,
                scope=self.scope, observation=observation,
                upload_artifacts=self.uploads.candidates() if self.uploads is not None else [],
                generated_downloads=('download' in self.scope.actions
                    and getattr(self.downloads, 'supports_generated', False) is True),
                completed_downloads=[DownloadSummary(**{k: item[k] for k in ('name', 'size', 'origin')})
                                     for item in self.download_results])
        except (ValueError, TypeError):
            self._finish('failed')
            return
        self._deadline = 0
        self.progress.emit('正在请求下一步建议；网页内容不构成操作授权')
        self._worker = BrowserProposalWorker(self.client, request, self.cancel, self)
        self._worker.finished.connect(self._proposal_ready)
        self._worker.start()

    @Slot()
    def _proposal_ready(self):
        worker, self._worker = self._worker, None
        if worker is None:
            return
        request, result, error = worker.request, worker.result, worker.error
        worker.deleteLater()
        if self._terminal is not None:
            self._emit_terminal()
            return
        if not self._active():
            self._finish('cancelled')
            return
        if error:
            # A provider may have charged before the response was lost. Do not
            # repeat the request under a new identifier here.
            self._finish('unknown')
            return
        try:
            proposal = validate_browser_step(request, BrowserStepProposal.model_validate(result))
            self._dispatch(request, proposal)
        except (ValueError, TypeError, OSError, RuntimeError):
            self._finish('failed')

    def _dispatch(self, request, proposal):
        if not self._active():
            self._finish('cancelled')
            return
        action = proposal.action
        if action == 'ask':
            self._finish('needs_input', proposal.model_dump())
            return
        if action == 'finish':
            self._recheck_completion(request, proposal)
            return
        if action == 'observe':
            self._observe()
            return
        if action == 'wait':
            if not self.observer.matches(self.lease, request.observation):
                self._finish('unknown')
                return
            self._deadline = time.monotonic() + 10
            self.progress.emit('等待页面更新，随后重新观察')
            def waited():
                if not self._active():
                    return
                if not self.observer.matches(self.lease, request.observation):
                    self._finish('unknown')
                    return
                self._observe()
            QTimer.singleShot(int(proposal.value), self, waited)
            return
        self._deadline = time.monotonic() + 45
        self.progress.emit('正在进行本地范围与授权检查')
        if action == 'upload':
            if self.uploads is None:
                self._finish('needs_input', {'reason':'upload_unavailable'})
            elif not self.observer.matches(self.lease, request.observation):
                self._finish('unknown')
            else:
                self._deadline = time.monotonic() + 300
                self.uploads.request(request.observation, proposal, self._upload_done)
        elif action == 'download':
            if self.downloads is None:
                self._finish('needs_input', {'reason':'download_unavailable'})
            else:
                self._deadline = time.monotonic() + 300
                self.downloads.begin(request.observation, proposal.target, self._download_done)
        elif action == 'login':
            if not self.observer.matches(self.lease, request.observation):
                self._finish('unknown')
            elif self.login is None:
                self._finish('needs_input', {'reason':'saved_login_unavailable'})
            else:
                self.login.fill(self._action_done)
        elif action == 'navigate':
            if self.navigation is None:
                self._finish('failed')
                return
            self.navigation.navigate(proposal.url, self._action_done)
        elif action == 'scroll':
            self.observer.scroll(self.lease, request.observation, proposal.value, callback=self._action_done)
        elif action == 'click':
            self.observer.click(self.lease, request.observation, proposal.target, callback=self._action_done)
        else:
            self.observer.edit(self.lease, request.observation, proposal.target,
                               action, proposal.value, callback=self._action_done)

    def _download_done(self, status, record):
        if not self._active():
            self._finish('cancelled')
        elif status == 'downloaded' and isinstance(record, dict) and record.get('task_id') == self.task_id:
            if self._verification_worker is not None:
                self._finish('unknown')
                return
            self._deadline = 0
            self.progress.emit('文件已保存，正在后台校验完整性并登记下载回执。')
            self._verification_worker = DownloadVerificationWorker(record, self.cancel, self)
            self._verification_worker.finished.connect(self._verification_ready)
            self._verification_worker.start()
        else:
            self._finish('unknown' if status == 'unknown' else 'needs_input')

    @Slot()
    def _verification_ready(self):
        worker, self._verification_worker = self._verification_worker, None
        if worker is None:
            return
        result = worker.result
        worker.deleteLater()
        if self._terminal is not None:
            self._emit_terminal()
            return
        if not self._active():
            self._finish('cancelled')
            return
        try:
            if result is None or self.downloads is None:
                raise ValueError('Download verification failed')
            record = self.downloads.commit_verified(result)
            self.download_results.append(record)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            self._finish('unknown')
            return
        self.progress.emit('下载完整性已校验并保存回执；业务内容仍需核验。')
        QTimer.singleShot(0, self._observe)

    def _action_done(self, status):
        if not self._active():
            self._finish('cancelled')
        elif status in {'loaded', 'dispatched'}:
            # Avoid recursive callbacks and reobserve after every action.
            QTimer.singleShot(0, self._observe)
        else:
            self._finish('unknown' if status == 'unknown' else 'needs_input')

    def _upload_done(self, status):
        if self._terminal is not None:
            self._emit_terminal()
        else:
            self._action_done(status)

    def _recheck_completion(self, request, proposal):
        """Re-read natively, without another paid call or trusting model metadata.

        This proves only current quoted evidence, not business success. The host
        still needs an independent goal/receipt verifier before succeeding.
        """
        original = request.observation
        if original is None or not self.observer.matches(self.lease, original):
            self._finish('unknown')
            return
        self._deadline = time.monotonic() + 10
        self._generation += 1
        generation = self._generation
        self.progress.emit('正在重新读取页面并核对完成依据；尚未确认业务成功')

        def checked(fresh):
            if generation != self._generation or not self._active():
                return
            if (fresh is None or fresh.origin != original.origin
                    or fresh.page_version != original.page_version
                    or not self.observer.matches(self.lease, fresh)
                    or not proposal.evidence.strip() or proposal.evidence not in fresh.text):
                self._finish('unknown')
                return
            self.completion_evidence = {
                'origin': fresh.origin, 'page_version': fresh.page_version,
                'evidence_sha256': sha256(proposal.evidence.encode('utf-8')).hexdigest(),
            }
            self._finish('needs_verification', proposal.model_dump())

        self.observer.observe(self.lease, checked)

    def _finish(self, status, detail=None):
        if not self._running or self._terminal is not None:
            return
        self._terminal = (status, detail)
        self._generation += 1
        self.timer.stop()
        if self.login is not None:
            self.login.close()
        if self.downloads is not None:
            self.downloads.close()
        if self.uploads is not None:
            self.uploads.close()
        if self.navigation is not None:
            self.navigation.cancel()
        if (self._worker is not None or self._verification_worker is not None
                or self.uploads is not None and self.uploads.isRunning()):
            self.cancel.set()
            return  # Keep the QObject/worker alive until the actual thread exits.
        self._emit_terminal()

    def _emit_terminal(self):
        if (self._terminal is not None and self._running and self._worker is None
                and self._verification_worker is None
                and (self.uploads is None or not self.uploads.isRunning())):
            self._running = False
            self.finished.emit(*self._terminal)
