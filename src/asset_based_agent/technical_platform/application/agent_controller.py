"""AgentController：提交/停止；后台提交不阻塞 UI 线程。"""
from .commands import StopOperation, SubmitMessage


class AgentController:
    def __init__(self, kernel, projector):
        self._kernel = kernel
        self._projector = projector

    def register(self, bus):
        bus.register(SubmitMessage, self.submit)
        bus.register(StopOperation, self.stop)

    async def submit(self, command):
        return await self._kernel.submit(command.session_id, 'main',
                                         {'text': command.text},
                                         wait=not command.background)

    async def stop(self, command):
        return await self._kernel.abort(command.operation_id)
