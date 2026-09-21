"""GUI-thread delivery pinned to the originating task, not the selected chat."""

from dataclasses import dataclass
from weakref import ref

from PySide6.QtCore import QObject, Slot

from .task_manager import TaskBinding


@dataclass(frozen=True)
class TaskDestination:
    store: object
    binding: TaskBinding

    @classmethod
    def resolve(cls, store, run_id):
        from .project_catalog import ProjectCatalog
        from .review_delivery import StepReviewStore
        store = store.active if isinstance(store, ProjectCatalog) else store
        run = store.run(run_id)
        store = store.store if isinstance(store, StepReviewStore) else store
        session = store.session(run['session'])
        return cls(store, TaskBinding(store.owner, session['project'], session['id'], run_id))

    def visible(self, window):
        from .project_catalog import ProjectCatalog
        current = window.store.active if isinstance(window.store, ProjectCatalog) else window.store
        return (current is not None and current.owner == self.binding.owner
                and current.path.resolve() == self.store.path.resolve()
                and window.project_id == self.binding.project_id
                and window.session_id == self.binding.session_id)


class TaskEventRelay(QObject):
    def __init__(self, window, worker, destination):
        super().__init__(window)
        self._window, self._worker = ref(window), ref(worker)
        self.destination = destination

    @property
    def window(self):
        return self._window()

    @property
    def worker(self):
        return self._worker()

    def active(self):
        return (self.window is not None and self.worker is not None
                and self.window.task_manager.owns(self.destination.binding, self.worker))

    @Slot(str)
    def progress(self, message):
        if self.active() and self.destination.visible(self.window):
            self.window.status.setText(message)

    @Slot(object)
    def output(self, issues):
        if self.active():
            self.window.receive_output(issues, destination=self.destination)

    @Slot(object)
    def completed(self, result):
        if self.active():
            self.window.completed(result, destination=self.destination)

    @Slot(str)
    def failed(self, message):
        if self.active():
            self.window.failed(message, destination=self.destination)

    @Slot()
    def finished(self):
        if self.active():
            self.window.finished(self.worker, self.destination)
        self.deleteLater()


class CompletionEventRelay(TaskEventRelay):
    """Only the two fixed auxiliary lifecycles are accepted, not model callbacks."""

    def __init__(self, window, worker, destination, kind):
        if kind not in {'understanding', 'annotation', 'consult'}:
            raise ValueError('Unknown worker lifecycle')
        super().__init__(window, worker, destination)
        self.kind = kind

    @Slot()
    def finished(self):
        if self.active():
            if self.kind == 'understanding':
                self.window.routing_finished(self.worker, self.destination)
            elif self.kind == 'consult':
                self.window.consult_finished(self.worker, self.destination)
            else:
                self.window.annotation_finished(self.worker, self.destination)
        self.deleteLater()
