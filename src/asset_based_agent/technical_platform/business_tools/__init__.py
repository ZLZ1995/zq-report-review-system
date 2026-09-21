"""S08：业务 Run Harness 的 Agent Tool 包装。

与现有 UI 驱动完全相同的 build_task_spec → start_run → execute_task 链路；
本包只做参数校验、权限回执核验、幂等与有界输出，不复制任何业务规则。
"""
from .service import BusinessRunService
from .tools import business_tools

__all__ = ['BusinessRunService', 'business_tools']
