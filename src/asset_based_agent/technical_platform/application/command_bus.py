"""CommandBus：命令类型 → controller 处理函数；未注册命令一律拒绝。"""


class UnknownCommand(Exception):
    pass


class CommandBus:
    def __init__(self):
        self._handlers = {}

    def register(self, command_type, handler):
        self._handlers[command_type] = handler

    def dispatch(self, command):
        handler = self._handlers.get(type(command))
        if handler is None:
            raise UnknownCommand(f'未注册命令: {type(command).__name__}')
        return handler(command)  # 可能是 coroutine，由调用方决定是否 await
