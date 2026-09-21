"""S06 客户端 ModelPort：经服务端流式端点接入模型。

与 agent_core 的分层约定：agent_core 保持零 I/O 契约，本包是唯一允许
使用 httpx 的模型接入层；客户端不持有任何供应商 API Key。
"""
from .message_mapping import entries_to_wire_messages
from .server_model_port import ServerModelPort
from .sse import iter_sse_events
from .token_provider import TokenManager

__all__ = [
    'ServerModelPort',
    'TokenManager',
    'entries_to_wire_messages',
    'iter_sse_events',
]
