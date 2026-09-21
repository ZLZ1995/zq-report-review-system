"""Lease-bound observation; fixed isolated script, no arbitrary evaluation API."""
import json
import weakref
from collections.abc import Callable
from uuid import uuid4

from PySide6.QtWebEngineCore import QWebEnginePage

from ..browser_contracts import (  # noqa: F401
    Choice,
    Control,
    Observation,
    RawObservation,
)
from .browser_observation import action_script, observation_script
from .browser_policy import credential_origin
from .browser_task_leases import BrowserTaskLeases, TabLease


class BrowserObserver:
    def __init__(self, leases: BrowserTaskLeases, page: QWebEnginePage, *,
                 can_observe: Callable[[TabLease, str], bool],
                 can_click: Callable[[TabLease, Observation, Control], bool] | None = None,
                 can_edit: Callable[[TabLease, Observation, Control, str, str], bool] | None = None,
                 can_scroll: Callable[[TabLease, Observation, str], bool] | None = None,
                 can_download: Callable[[TabLease, Observation, Control], bool] | None = None,
                 can_upload: Callable[[TabLease, str], bool] | None = None):
        if leases.tab_id(page) is None or not leases.session.owns_page(page):
            raise PermissionError('Unregistered observation page')
        self.leases, self._page, self._allowed = leases, weakref.ref(page), can_observe
        self._closed, self._epoch, self._nonce = False, 0, ''
        self._can_click = can_click
        self._can_edit = can_edit
        self._can_scroll = can_scroll
        self._can_download = can_download
        self._can_upload = can_upload
        self._observation: Observation | None = None
        self._snapshot = ''
        page.loadStarted.connect(self.invalidate)
        page.urlChanged.connect(self.invalidate)
        page.renderProcessTerminated.connect(self.invalidate)

    def invalidate(self, *_args) -> None:
        self._epoch += 1
        self._nonce = ''
        self._observation = None
        self._snapshot = ''

    def _origin(self, lease: TabLease) -> str | None:
        page = self._page()
        if (self._closed or not self.leases.valid(lease) or page is None
                or not self.leases.session.owns_page(page) or page.isLoading()
                or self.leases.tab_id(page) != lease.tab_id):
            return None
        try:
            origin = credential_origin(page.url().toString())
            return origin if self._allowed(lease, origin) is True else None
        except (ValueError, OSError, RuntimeError):
            return None

    def observe(self, lease: TabLease, callback: Callable[[Observation | None], None]) -> None:
        self._observation = None
        self._snapshot = ''
        origin = self._origin(lease)
        page = self._page()
        if origin is None or page is None:
            callback(None)
            return
        epoch, nonce = self._epoch, uuid4().hex
        self._nonce = nonce

        def receive(raw):
            result = None
            try:
                if (isinstance(raw, str) and len(raw) <= 100000 and self._epoch == epoch
                        and self._nonce == nonce and self._origin(lease) == origin):
                    data = RawObservation.model_validate_json(raw)
                    if data.nonce == nonce and data.origin == origin:
                        result = Observation(**data.model_dump(), page_version=epoch)
                        self._observation = result
                        self._snapshot = result.model_dump_json()
            except (ValueError, TypeError, RuntimeError):
                pass
            callback(result)

        try:
            include_files = self._can_upload is not None and self._can_upload(lease, origin) is True
            page.runJavaScript(observation_script(nonce, include_files=include_files), 1, receive)
        except (ValueError, OSError, RuntimeError):
            callback(None)

    def reserve_upload(self, lease: TabLease, observation: Observation, control_id: str) -> bool:
        """Consume native observation once; no file or website permission is granted."""
        try:
            control = next((c for c in observation.controls if c.id == control_id), None)
            return (self.matches(lease, observation) and control is not None
                    and control.kind == 'file' and not control.disabled
                    and self._can_upload is not None
                    and self._can_upload(lease, observation.origin) is True
                    and self.matches(lease, observation))
        finally:
            self._observation, self._snapshot = None, ''

    def click(self, lease: TabLease, observation: Observation, control_id: str, *,
              callback: Callable[[str], None]) -> None:
        self._act(lease, observation, control_id, 'click', '', callback=callback)

    def matches(self, lease: TabLease, observation: Observation) -> bool:
        return (self._observation is observation and observation.model_dump_json() == self._snapshot
                and self._epoch == observation.page_version and self._nonce == observation.nonce
                and self._origin(lease) == observation.origin)

    def resolve_download(self, lease: TabLease, observation: Observation, control_id: str, *,
                         callback: Callable[[str | None], None]) -> None:
        # Only native callers receive the resolved URL; it is not an LLM observation.
        self._act(lease, observation, control_id, 'download', '',
                  callback=lambda value: callback(value if value.startswith('https://') else None))

    def scroll(self, lease: TabLease, observation: Observation, direction: str, *,
               callback: Callable[[str], None]) -> None:
        self._act(lease, observation, '1', 'scroll', direction, callback=callback)

    def download_button(self, lease, observation, control_id, *, before_dispatch, callback):
        self._act(lease, observation, control_id, 'download_button', '',
                  before_dispatch=before_dispatch, callback=callback)

    def edit(self, lease: TabLease, observation: Observation, control_id: str,
             operation: str, value: str, *, callback: Callable[[str], None]) -> None:
        if operation not in {'fill', 'select'}:
            callback('rejected')
            return
        self._act(lease, observation, control_id, operation, value, callback=callback)

    def _act(self, lease: TabLease, observation: Observation, control_id: str,
             operation: str, value: str, *, callback: Callable[[str], None], before_dispatch=None) -> None:
        """Native action gate is mandatory. Dispatch is not business success.

        Unknown results must be reconciled by observing the site, not retried as
        writes. The caller must never implement can_click from webpage claims.
        """
        recorded, snapshot = self._observation, self._snapshot
        self._observation, self._snapshot = None, ''
        page = self._page()
        allowed = False
        try:
            control = next((c for c in observation.controls if c.id == control_id), None)
            if operation == 'scroll':
                control = Control(id='1', kind='button', text='当前页面视口', disabled=False)
            compatible = (control is not None and isinstance(value, str) and len(value) <= 4000 and (
                (operation == 'scroll' and value in {'up', 'down'})
                or (operation == 'click' and control.kind in {'button', 'link'})
                or (operation == 'download' and control.kind == 'link')
                or (operation == 'download_button' and control.kind == 'button')
                or (operation == 'fill' and control.kind == 'textfield')
                or (operation == 'select' and control.kind == 'select'
                    and value in {option.id for option in control.options})))
            allowed = (recorded is observation and observation.model_dump_json() == snapshot
                       and compatible and control is not None and not control.disabled
                       and self._origin(lease) == observation.origin and page is not None
                       and ((operation == 'scroll' and self._can_scroll is not None
                             and self._can_scroll(lease, observation, value) is True)
                            or (operation == 'click' and self._can_click is not None
                             and self._can_click(lease, observation, control) is True)
                            or (operation in {'download', 'download_button'} and self._can_download is not None
                                and self._can_download(lease, observation, control) is True)
                            or (operation in {'fill', 'select'} and self._can_edit is not None
                                and self._can_edit(lease, observation, control, operation, value) is True))
                       and self._epoch == observation.page_version and self._nonce == observation.nonce
                       and self._origin(lease) == observation.origin
                       and observation.model_dump_json() == snapshot)
        except (ValueError, TypeError, AttributeError, OSError, RuntimeError):
            allowed = False
        if not allowed or page is None:
            callback('rejected')
            return

        def receive(raw):
            status = 'unknown'
            try:
                if (self._epoch == observation.page_version and self._origin(lease) == observation.origin
                        and isinstance(raw, str) and len(raw) < (10000 if operation == 'download' else 100)):
                    data = json.loads(raw)
                    if (operation == 'download' and isinstance(data, dict)
                            and set(data) == {'status', 'url'} and data['status'] == 'resolved'
                            and isinstance(data['url'], str) and len(data['url']) <= 8192
                            and credential_origin(data['url']) == observation.origin):
                        status = data['url']
                    elif data in ({'status': 'rejected'}, {'status': 'dispatched'}):
                        status = data['status']
            except (ValueError, TypeError, RuntimeError):
                pass
            callback(status)

        try:
            if operation == 'download_button' and (before_dispatch is None or before_dispatch() is not True):
                callback('rejected')
                return
            page.runJavaScript(action_script(observation.nonce, observation.origin, control_id, operation, value), 1, receive)
        except (ValueError, OSError, RuntimeError):
            callback('unknown')

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.invalidate()
        page = self._page()
        if page is not None and self.leases.session.owns_page(page):
            for signal in (page.loadStarted, page.urlChanged, page.renderProcessTerminated):
                signal.disconnect(self.invalidate)
