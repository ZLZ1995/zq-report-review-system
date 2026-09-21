"""Native input revokes automation leases without swallowing the user's event."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QWidget


class BrowserTakeover(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.closed = False
        application = QApplication.instance()
        if application is None:
            raise RuntimeError('Browser requires application')
        self.application = application
        application.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (not self.closed and event.type() in {
            QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel,
            QEvent.Type.TouchBegin, QEvent.Type.InputMethod,
        } and isinstance(watched, QWidget) and self.panel.isAncestorOf(watched)):
            target: QWidget | None = watched
            while target is not None and not isinstance(target, QWebEngineView):
                target = target.parentWidget()
            view = target if target is not None else self.panel.current_view()
            if view is not None and self.panel.task_leases.takeover(view.page()):
                self.panel.notice(view, '你已接管此标签，Agent 后续操作已停止；继续需重新授权。')
        return False

    def close(self):
        if not self.closed:
            self.closed = True
            self.application.removeEventFilter(self)
