"""七个业务工具的 AgentTool 实现；同步服务调用一律进线程，异常映射为有界失败。"""
import asyncio

from ..agent_core.contracts import ToolDescriptor, ToolResult
from ..agent_core.errors import AgentError, ToolFailed

_EXECUTE_SCHEMA = {
    'type': 'object',
    'required': ['skill_id', 'skill_version', 'skill_hash', 'target_file_ids',
                 'reference_file_ids', 'user_goal', 'confirmed_facts',
                 'permission_receipt', 'idempotency_key'],
    'properties': {
        'skill_id': {'type': 'string'},
        'skill_version': {'type': 'string'},
        'skill_hash': {'type': 'string'},
        'target_file_ids': {'type': 'array', 'items': {'type': 'string'}},
        'reference_file_ids': {'type': 'array', 'items': {'type': 'string'}},
        'user_goal': {'type': 'string'},
        'confirmed_facts': {'type': 'array', 'items': {'type': 'string'}},
        'permission_receipt': {'type': 'object'},
        'idempotency_key': {'type': 'string'},
        'input_roles': {'type': 'object'},
        'instructions': {'type': 'string'},
    },
}

_RUN_STATES = {'succeeded': 'succeeded', 'failed': 'failed', 'cancelled': 'aborted'}


class BusinessTool:
    def __init__(self, descriptor, invoke):
        self.descriptor = descriptor
        self._invoke = invoke

    async def execute(self, context, arguments, cancel):
        try:
            return await asyncio.to_thread(self._invoke, arguments or {}, cancel)
        except AgentError as exc:
            return ToolResult(status='failed', error_code=exc.code, content=str(exc))
        except Exception as exc:  # noqa: BLE001 - 工具边界不泄露堆栈
            return ToolResult(status='failed', error_code=ToolFailed.code,
                              content=f'工具内部错误（{type(exc).__name__}）')


def business_tools(service):
    """把 BusinessRunService 包装成七个 Agent Tool。"""
    def inspect(arguments, cancel):
        payload = service.inspect_files()
        return ToolResult(status='succeeded', result=payload,
                          content=f"项目内共 {len(payload['files'])} 个文件。")

    def analyze(arguments, cancel):
        payload = service.analyze_roles(arguments.get('file_ids', []))
        return ToolResult(status='succeeded', result=payload, content='文件角色识别完成。')

    def execute(arguments, cancel):
        payload = service.execute_skill_plan(
            cancel_event=cancel.threading_event, **arguments)
        status = _RUN_STATES.get(payload['state'], 'unknown')
        receipt = arguments.get('permission_receipt')
        granted = sorted({str(g) for g in receipt.get('granted', [])}) \
            if isinstance(receipt, dict) else []
        return ToolResult(
            status=status, content=payload['summary'], result=payload,
            error_code={'failed': 'tool.failed', 'aborted': 'agent.cancelled'}.get(status, ''),
            receipts=({'granted': granted},))

    def query(arguments, cancel):
        payload = service.query_run(str(arguments.get('run_id', '')))
        return ToolResult(status='succeeded', result=payload, content=payload['summary'])

    def cancel_business_run(arguments, cancel):
        payload = service.cancel_run(str(arguments.get('run_id', '')))
        return ToolResult(status='succeeded', result=payload,
                          content=f"任务状态：{payload['state']}")

    def list_artifacts(arguments, cancel):
        payload = service.list_final_artifacts(str(arguments.get('run_id', '')))
        return ToolResult(status='succeeded', result=payload,
                          content=f"最终成果 {len(payload['artifacts'])} 项。")

    def annotate(arguments, cancel):
        payload = service.annotate(str(arguments.get('run_id', '')),
                                   arguments.get('selected', []),
                                   str(arguments.get('directory', '')))
        return ToolResult(status='succeeded', result=payload,
                          content=f"已生成 {len(payload['artifacts'])} 份标注副本；原件未修改。")

    return [
        BusinessTool(ToolDescriptor(
            name='inspect_project_files',
            description='列出当前项目已登记文件的元数据（不含路径与内容）',
            input_schema={'type': 'object'}, risk='local_readonly'), inspect),
        BusinessTool(ToolDescriptor(
            name='analyze_file_roles',
            description='按文件名与格式推断文件角色（报告/说明/测算表/参考资料）',
            input_schema={'type': 'object', 'required': ['file_ids']},
            risk='local_readonly'), analyze),
        BusinessTool(ToolDescriptor(
            name='execute_skill_plan',
            description='按已确认参数执行业务 Skill（审核/生成），复用既有硬门禁与验收链',
            input_schema=_EXECUTE_SCHEMA, risk='network_write'), execute),
        BusinessTool(ToolDescriptor(
            name='query_business_run',
            description='查询业务 run 的状态、有界摘要与最终成果引用',
            input_schema={'type': 'object', 'required': ['run_id']},
            risk='local_readonly'), query),
        BusinessTool(ToolDescriptor(
            name='cancel_business_run',
            description='取消排队中或执行中的业务 run（协作式取消）',
            input_schema={'type': 'object', 'required': ['run_id']},
            risk='process'), cancel_business_run),
        BusinessTool(ToolDescriptor(
            name='list_final_artifacts',
            description='列出业务 run 的最终成果（过滤内部状态文件，不含路径）',
            input_schema={'type': 'object', 'required': ['run_id']},
            risk='local_readonly'), list_artifacts),
        BusinessTool(ToolDescriptor(
            name='annotate_reviewed_files',
            description='为已审核问题生成保真标注副本（docx/xlsx），不修改原件',
            input_schema={'type': 'object',
                          'required': ['run_id', 'selected', 'directory']},
            risk='copy_modify'), annotate),
    ]
