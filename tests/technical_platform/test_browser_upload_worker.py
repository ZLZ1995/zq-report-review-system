import os
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from test_browser_upload_authorization import ready


def test_upload_preparation_runs_off_gui_and_returns_bound_payload(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import browser_upload_worker as module
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store, _, scope, reference = ready(tmp_path)
    main_thread = threading.get_ident()
    original = module.prepare_upload
    seen = []
    def prepare(*args):
        seen.append(threading.get_ident())
        return original(*args)
    monkeypatch.setattr(module, 'prepare_upload', prepare)
    worker = module.UploadPreparationWorker(UploadAuthorization(store), scope.model_dump(
        exclude={'artifact', 'receipt_id'}), reference, threading.Event(), confirmed=True)
    worker.start()
    assert worker.wait(15000)
    assert seen and seen[0] != main_thread
    permit, payload = worker.result
    assert payload == b'synthetic artifact, not a business document'
    assert permit.scope.identity == scope.identity
    assert permit.scope.artifact.path != scope.artifact.path
    assert permit.scope.artifact.sha256 == scope.artifact.sha256
    worker.deleteLater()


def test_cancelled_or_unconfirmed_upload_worker_returns_no_payload(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    from asset_based_agent.technical_platform.browser_upload_worker import (
        UploadPreparationWorker,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store, _, scope, reference = ready(tmp_path)
    for confirmed in (False, True):
        cancel = threading.Event()
        if confirmed: cancel.set()
        worker = UploadPreparationWorker(UploadAuthorization(store), scope.model_dump(
            exclude={'artifact', 'receipt_id'}), reference, cancel, confirmed=confirmed)
        worker.start()
        assert worker.wait(15000)
        assert worker.result is None
        worker.deleteLater()


def test_cancel_during_background_preparation_does_not_authorize(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import browser_upload_worker as module
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store, _, scope, reference = ready(tmp_path)
    entered, resume, cancel = threading.Event(), threading.Event(), threading.Event()
    original = module.prepare_upload
    authorization = UploadAuthorization(store)
    def prepare(*args):
        entered.set()
        assert resume.wait(10)
        return original(*args)
    def forbidden_authorize(*args, **kwargs):
        raise AssertionError('Cancelled preparation must not authorize')
    called = []
    def authorize(*args, **kwargs):
        called.append(True)
        forbidden_authorize(*args, **kwargs)
    monkeypatch.setattr(module, 'prepare_upload', prepare)
    monkeypatch.setattr(authorization, 'authorize', authorize)
    worker = module.UploadPreparationWorker(authorization, scope.model_dump(
        exclude={'artifact', 'receipt_id'}), reference, cancel, confirmed=True)
    worker.start()
    try:
        assert entered.wait(10)
        cancel.set()
    finally:
        resume.set()
        assert worker.wait(15000)
    assert worker.result is None
    assert not called
    worker.deleteLater()
