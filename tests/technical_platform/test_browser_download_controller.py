from types import SimpleNamespace

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest


class Event:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in self.callbacks[:]:
            callback(*args)


class Request:
    def __init__(self, page):
        self.source = page
        self.status = QWebEngineDownloadRequest.DownloadState.DownloadRequested
        self.stateChanged = Event()
        self.receivedBytesChanged = Event()
        self.totalBytesChanged = Event()
        self.accepted = False

    def page(self): return self.source
    def id(self): return 1
    def url(self): return QUrl('https://example.com/file')
    def isSavePageDownload(self): return False
    def suggestedFileName(self): return 'test.txt'
    def setDownloadDirectory(self, value): self.directory = value
    def setDownloadFileName(self, value): self.filename = value
    def receivedBytes(self): return 4
    def totalBytes(self): return -1
    def state(self): return self.status
    def accept(self): self.accepted = True

    def cancel(self):
        self.status = QWebEngineDownloadRequest.DownloadState.DownloadCancelled
        self.stateChanged.emit(self.status)


def setup_controller(tmp_path, choose=True):
    from asset_based_agent.technical_platform.browser_download_controller import (
        BrowserDownloads,
    )
    page = object()
    profile = SimpleNamespace(downloadRequested=Event())
    journal = SimpleNamespace(track=lambda target: None, forget=lambda stage: None)
    session = SimpleNamespace(profile=profile, download_journal=journal,
                              owns_page=lambda candidate: candidate is page)
    destination = tmp_path/'result.txt'
    controller = BrowserDownloads(session, lambda name: destination if choose else None)
    return controller, Request(page), destination


def test_download_controller_completion_and_duplicate_terminal(tmp_path):
    controller, request, destination = setup_controller(tmp_path)
    controller.request(request)
    assert request.accepted
    from pathlib import Path
    (Path(request.directory)/request.filename).write_bytes(b'data')
    request.status = QWebEngineDownloadRequest.DownloadState.DownloadCompleted
    request.stateChanged.emit(request.status)
    request.stateChanged.emit(request.status)
    assert destination.read_bytes() == b'data'
    assert controller.records[1].status == 'completed'
    assert controller.records[1].total == -1
    controller.close()


def test_download_decline_and_foreign_page(tmp_path):
    controller, request, destination = setup_controller(tmp_path, False)
    controller.request(request)
    assert not request.accepted
    request.source = object()
    controller.request(request)
    assert not request.accepted
    request.source = None
    controller.request(request)
    assert not request.accepted
    assert request.status == QWebEngineDownloadRequest.DownloadState.DownloadCancelled
    assert not destination.exists()
    assert not list(tmp_path.iterdir())
    controller.close()


def test_download_close_cancels_without_publishing(tmp_path):
    controller, request, destination = setup_controller(tmp_path)
    controller.request(request)
    controller.close()
    assert request.status == QWebEngineDownloadRequest.DownloadState.DownloadCancelled
    assert controller.records[1].status == 'cancelled'
    assert not destination.exists()
    assert controller.records[1].cleanup_pending
    assert list(tmp_path.iterdir()) == [controller.records[1].target.stage]


def test_download_storage_index_failure_cancels_before_accept(tmp_path):
    import sqlite3
    controller, request, destination = setup_controller(tmp_path)
    def unavailable(_name):
        raise sqlite3.OperationalError('synthetic locked storage index')
    controller.choose = unavailable
    messages = []
    controller.rejected.connect(messages.append)
    controller.request(request)
    assert not request.accepted and not destination.exists()
    assert messages and 'synthetic' not in messages[0]
    controller.close()


def test_download_journal_failure_prevents_network_write(tmp_path):
    import sqlite3
    controller, request, destination = setup_controller(tmp_path)
    def fail(_target):
        raise sqlite3.OperationalError('synthetic journal failure')
    controller.journal.track = fail
    controller.request(request)
    assert not request.accepted and not destination.exists()
    assert not list(tmp_path.iterdir())
    assert not controller.records
    controller.close()
