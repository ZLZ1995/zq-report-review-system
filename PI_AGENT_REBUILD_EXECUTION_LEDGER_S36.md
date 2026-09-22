# PI Agent 重构执行账本 S36

## 问题

历史项目资料虽然已经被列入 ContextBuilder 的上下文，但只显示文件名，没有显示稳定的 `file_id`。模型在用户说“历史对话中的文件”“刚才的工作簿”时无法把自然语言指代转换为 `read_project_file` 所需的参数，容易退回要求重新上传或错误声称没有资料。

## 修改

- `agent_core/context_builder.py` 的历史资料目录现在以 `name[id=file_id]` 形式提供。
- 保持安全边界：历史文件仍不是当前 operation 的默认写入绑定；只有模型基于用户请求调用只读检查/读取工具后才能使用，不自动改写原件。
- 增加回归测试，验证历史资料目录包含名称和稳定 ID。

## 验收

- ContextBuilder 专项：22 passed。
- Agent rebuild 全量：399 passed, 9 xfailed，耗时 54.26s。

## 边界

- 该修复解决了“模型无法定位历史文件”的上下文问题，不等于允许模型无条件把历史文件作为输出目标；输出文件仍须显式绑定并经过工具/权限策略校验。
- 需要在真实模型服务上复测指代解析和 `inspect_project_files`/`read_project_file` 调用链。
