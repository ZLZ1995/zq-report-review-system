"""Page and network boundaries; no generic webpage-to-host bridge.

Login capture is attached separately in ApplicationWorld, never MainWorld.
"""
from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

from .browser_policy import navigation_url, request_allowed


class BrowserRequestInterceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        main = info.resourceType() == QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame
        if not request_allowed(info.requestUrl().toString(), main_frame=main):
            info.block(True)


class BrowserPage(QWebEnginePage):
    blocked = Signal(str)

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._task_navigation_owner = None
        self._task_navigation_guard = None
        self.certificateError.connect(lambda error: error.rejectCertificate())
        self.permissionRequested.connect(lambda permission: permission.deny())
        self.fileSystemAccessRequested.connect(lambda request: request.reject())

    def set_task_navigation_guard(self, owner, guard):
        if self._task_navigation_owner is not None:
            raise PermissionError('Page already has task navigation guard')
        self._task_navigation_owner, self._task_navigation_guard = owner, guard

    def clear_task_navigation_guard(self, owner):
        if self._task_navigation_owner is owner:
            self._task_navigation_owner, self._task_navigation_guard = None, None

    def take_over_navigation(self):
        """Trusted native user input only; also clears a cancelled task's guard."""
        self._task_navigation_owner, self._task_navigation_guard = None, None

    def acceptNavigationRequest(self, url: QUrl | str, navigation_type, is_main_frame: bool) -> bool:
        try:
            navigation_url(url if isinstance(url, str) else url.toString())
        except ValueError:
            # Do not echo the URL: it could contain a password or sensitive query.
            self.blocked.emit('已阻止不安全的网页地址。')
            return False
        if is_main_frame and self._task_navigation_guard is not None:
            try:
                allowed = self._task_navigation_guard(url if isinstance(url, str) else url.toString()) is True
            except Exception:  # noqa: BLE001 - fail closed at the Qt virtual callback boundary
                allowed = False
            if not allowed:
                self.blocked.emit('已阻止超出当前任务授权范围的网页跳转。')
                return False
        return True

    def chooseFiles(self, mode, old_files, accepted_mime_types):
        # File transfer will use the explicit artifact/target approval workflow.
        self.blocked.emit('上传文件需要先确认目标网站和授权成果。')
        return []
