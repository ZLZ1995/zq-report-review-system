# Kimi Work 工程施工文件：对话时间线、运行状态与成果归属修复

## 0. 执行目标

本文件供 Kimi Work 直接读取并实施。目标是一次性解决以下已经复现并有源码证据的问题：

1. 同一条助手回复同时出现在对话正文和输入框上方，形成重复显示；
2. “正在理解、正在执行、已完成、失败”等运行状态固定在输入框上方，而不是进入对应对话轮次；
3. “添加本轮资料，用自然语言描述任务。原始文件只读。”被当作状态栏内容，长期占据输入框上方；
4. 历史任务生成的 Word/PDF/PNG 等成果每次刷新后都被追加到全部消息末尾，看起来像是最新回复生成的文件；
5. 切换会话时，旧会话正在流式输出的状态或正文可能污染新会话；
6. 对话面板采用“先渲染全部消息，再渲染全部 runs”的双列表拼接方式，无法形成真正的消息时间线。

此次调整属于客户端 UI/Harness 与本地会话数据模型修复，不属于模型、Agent 推理逻辑或业务 Skill 修复。不得修改业务 Skill 模板、评估明细表模板、报告审核规则或服务端计费逻辑。

基线分支：`kimi/pi-agent-core-rebuild`

已存在且不得回退的相关提交：

- `4d601d8 fix: keep streaming replies scoped to conversation panel`
- 该提交已完成流式文本批量刷新和 Agent 轮次的会话绑定；本轮应在其基础上继续，不得恢复逐 token 重绘，也不得重新允许跨会话写入。

---

## 1. 已确认问题、产生位置与根因

### P1：完整回复显示两次

#### 现象

同一助手回复在对话正文中显示一次，又以浅灰色文字在输入框上方显示一次。

#### 产生位置

文件：`src/asset_based_agent/technical_platform/app.py`

- `_on_agent_done()`：完成后向 `messages` 表写入助手回复，并调用 `render_messages()`；
- 同一函数随后调用 `self.status.setText(reply)`；
- `_build()` 又把 `self.status` 这个 `QLabel` 固定插入在 `transcript` 和 `composer_card` 之间。

当前关键代码位置约为：

- `_on_agent_done`：L402—L415；
- `self.status` 创建与 `middle.addWidget(self.status)`：L526—L529。

#### 根因

不是数据库重复消息。运行库证据显示同一轮只有一条 `assistant` 消息。重复来自两个 UI 控件同时展示同一字符串：

- 正文来源：`QTextBrowser transcript`；
- 重复来源：`QLabel status`。

### P2：运行状态固定在输入框上方

#### 现象

“正在生成”“正在理解”“等待补充信息”“任务完成”等状态与聊天时间线脱离，固定占据输入框上方。

#### 产生位置

文件：`src/asset_based_agent/technical_platform/app.py`

- `_build()` 将 `self.status` 放在 transcript 之后、composer 之前；
- 文件中存在大量 `self.status.setText(...)`，同时承载项目提示、运行阶段、错误、完成结果、登录状态、更新状态、浏览器状态等不同语义；
- `reload_projects()` 约 L832 将“添加本轮资料，用自然语言描述任务。原始文件只读。”写入同一状态控件。

#### 根因

单一 `QLabel` 被错误地当成全平台消息总线，并且其布局位置与输入框绑定。不同生命周期、不同作用域的信息没有分类：

- 会话级运行状态；
- 当前轮次状态；
- 全局服务状态；
- 空会话提示；
- 可操作错误。

### P3：历史成果被挂到最新回复下面

#### 现象

以前任务生成的 Word、PDF、PNG 在发送新问题后仍出现在最新回复之后，用户会误认为这些文件由最新回复生成。

#### 产生位置

文件：`src/asset_based_agent/technical_platform/app.py`

- `render_messages()` 约 L1030 起先遍历 `messages`；
- 消息循环结束后，约 L1076 再执行 `for run in self.store.runs(self.session_id)`；
- 每个历史 run 的 artifacts 被统一追加到 `content` 最后，约 L1110—L1150。

数据层位置：

- `src/asset_based_agent/technical_platform/store.py`
- `messages` 表只有 `session/role/text/created`；
- `runs` 表只有 `session/state/snapshot/result/created`；
- `runs` 没有 `source_message_id` 或 `assistant_message_id`，无法知道成果属于哪一条消息。

#### 根因

当前 UI 不是时间线投影，而是两个集合的简单拼接：

```text
全部 messages
+
全部 runs 的成果
```

因此每次出现新消息，历史成果都会自然落到最新消息之后。这不是 Skill 重复执行，也不是 Agent 重新生成文件。

### P4：旧运行状态跨会话污染

#### 现象

切换会话后，旧会话正在产生的流式内容或完成回调仍可能显示到当前窗口。

#### 当前基线状态

提交 `4d601d8` 已新增 `_agent_session_id`，并在增量、完成和渲染阶段检查目标会话。本轮必须保留并补足测试，不得重新使用裸 `self.session_id` 作为异步回调的写入目标。

---

## 2. 目标交互规范

### 2.1 对话时间线

每个会话只显示自己的时间线，顺序必须是：

```text
用户消息
本轮运行状态（临时、原位更新）
助手回复
该轮产生的最终成果
下一条用户消息
下一轮状态/回复/成果
```

历史成果必须留在产生它的助手消息下面，不得因发送新消息而移动到页面末尾。

### 2.2 状态分类

按以下规则处理所有现有 `self.status.setText(...)`：

| 状态类型 | 示例 | 正确位置 | 是否持久化 |
|---|---|---|---|
| 当前轮次阶段 | 正在理解、正在生成、正在执行 Skill | 对话时间线中的临时执行卡 | 否，只保存关键事件 |
| 当前轮次终态 | 完成、失败、取消、等待补充 | 对应轮次的事件/助手消息 | 是 |
| 空会话说明 | 添加本轮资料，用自然语言描述任务 | transcript 空状态 | 否 |
| 全局连接状态 | 服务已连接、网络不可用 | 左侧账号区或全局通知 | 按需 |
| 更新状态 | 正在下载、验签失败 | 更新入口附近或全局通知 | 按需 |
| 浏览器状态 | 浏览器无法启动 | 浏览器面板或全局通知 | 按需 |
| 输入校验 | 未选文件、名称无效 | 输入框附近短提示或对话事件 | 否 |

输入框上方不得保留长期可见的通用状态栏。

### 2.3 成果展示

- 对用户可见的最终成果继续显示在对话中；
- 过程 JSON、诊断文件等非用户成果继续受 `user_artifacts()` 过滤；
- 每个成果卡必须属于唯一 run，并关联唯一助手消息或任务事件；
- 普通聊天回复不得带出任何历史成果；
- 历史未能可靠关联的旧 run 不得挂到最新消息后，可进入独立“历史成果（旧版本）”区域或右侧文件面板。

---

## 3. 数据模型修改方案

### 3.1 本地数据库版本

文件：`src/asset_based_agent/technical_platform/local_migrations.py`

- 将 `SCHEMA_VERSION` 从 `13` 升级为 `14`；
- 保持已有 v1—v13 数据可原地升级；
- 不删除、不覆盖任何历史消息、runs 或附件。

### 3.2 新增关联表

推荐新增表，不直接破坏旧 `messages`/`runs` 表：

```sql
CREATE TABLE run_message_links (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    source_message_id INTEGER REFERENCES messages(id),
    assistant_message_id INTEGER REFERENCES messages(id),
    relation TEXT NOT NULL CHECK(relation IN ('exact','legacy_inferred','legacy_unlinked')),
    created_at TEXT NOT NULL
);

CREATE INDEX run_message_links_by_assistant
ON run_message_links(session_id, assistant_message_id);
```

约束：

- `run_id` 只能关联同一 session 内的消息；
- 新运行必须使用 `relation='exact'`；
- 不允许将一个 run 绑定到其他会话；
- 消息或 run 不得因关联失败而被删除。

### 3.3 Store API

文件：`src/asset_based_agent/technical_platform/store.py`

实施以下 API 调整：

1. `append(session_id, role, text)` 返回新消息的整数 ID；旧调用方忽略返回值时保持兼容；
2. 新增 `link_run_messages(run_id, source_message_id=None, assistant_message_id=None, relation='exact')`；
3. 新增 `run_links(session_id)` 或 `runs_with_message_links(session_id)`；
4. 新增归属校验，拒绝跨 session 关联；
5. 所有写入使用同一事务；完成消息与 run 关联必须原子提交，避免消息存在但成果悬空。

### 3.4 历史数据迁移

不得拍脑袋把所有历史 run 绑定到最后一条回复。

迁移策略：

1. 读取 run 的最终 `events.created`；
2. 在同一 session 中查找终态之后紧邻的 assistant 消息；
3. 只有在时间窗口、顺序和唯一性都成立时标记 `legacy_inferred`；
4. 无法唯一判断的标记 `legacy_unlinked`，不放在最新回复下面；
5. 保留迁移审计数量：exact/inferred/unlinked；
6. 迁移必须幂等，重复启动不得产生重复关联。

如果旧数据无法可靠推断，应优先保留数据和诚实标注，禁止伪造精确归属。

---

## 4. UI/Harness 修改方案

### 4.1 删除固定状态栏布局

文件：`src/asset_based_agent/technical_platform/app.py`

- 删除或停止执行 `middle.addWidget(self.status)`；
- 不再让 `status QLabel` 占据 transcript 与 composer 之间的布局空间；
- 如果短期需要兼容旧调用，可保留一个不可见的状态适配器，但不得继续显示完整回复；
- 最终应逐步移除所有直接 `self.status.setText(...)`，改为作用域明确的状态控制接口。

### 4.2 新增状态控制器

建议新增文件：

`src/asset_based_agent/technical_platform/conversation_status.py`

提供接口：

```python
set_turn_phase(session_id, operation_id, text)
complete_turn(session_id, operation_id, summary)
fail_turn(session_id, operation_id, error_code, summary)
clear_turn_phase(session_id, operation_id)
set_global_notice(kind, text)
```

规则：

- 会话状态必须携带 `session_id`；
- 异步回调必须携带 `operation_id` 或 run_id；
- 当前 UI 只渲染当前 session 的状态；
- 切换会话后旧会话状态继续保存在其控制器中，但不得覆盖新会话；
- 完成后临时阶段卡被最终消息替换，不形成重复内容。

### 4.3 对话时间线投影

建议新增：

`src/asset_based_agent/technical_platform/conversation_timeline.py`

定义稳定的 UI ViewModel：

```python
TimelineItem(
    kind='user' | 'assistant' | 'event' | 'live_status' | 'artifacts' | 'legacy_artifacts',
    message_id=None,
    run_id=None,
    operation_id=None,
    created_at='',
    payload={...},
)
```

投影过程：

1. 读取当前 session 的 messages；
2. 读取 run_message_links；
3. 将关联成果插入对应 assistant message 之后；
4. 将当前轮次 live status 插在对应 user message 之后；
5. 未关联的 legacy run 进入独立旧成果区域，不追加到最后一条回复；
6. `render_messages()` 只负责渲染 TimelineItem，不再自行访问和拼接全部 runs。

### 4.4 回复完成逻辑

修改 `_on_agent_done()`：

- 回复只写入一次消息表；
- 禁止再执行 `self.status.setText(reply)`；
- 清除对应 live status；
- 普通聊天 operation 没有 artifacts，不创建成果节点；
- 若 operation 产生业务 run，则通过关联 API 绑定助手消息；
- 仅当前会话触发可见重绘，原会话仍应正确落库。

### 4.5 业务任务完成逻辑

检查 `completed()`、`routing_finished()`、浏览器完成、审核导出、批注生成、组合计划完成等路径。

每条产生用户成果的路径都必须：

1. 创建/取得本轮助手消息 ID；
2. 将 run 绑定到该消息；
3. 再提交最终状态；
4. 失败、取消、等待补充同样产生明确时间线事件，但不展示不存在的成果。

不得只修 Agent chat 路径而遗漏旧业务 TaskWorker 路径。

### 4.6 空状态与全局状态

- “添加本轮资料……”移动到 transcript 空状态模板；
- 左侧账号区显示连接状态；
- 更新状态靠近“下载并安装更新”入口；
- 浏览器状态进入浏览器面板；
- 无法归类的全局错误使用非阻塞通知或必要弹窗，不得重新塞回输入框上方。

---

## 5. 文件施工清单

必须检查并按需修改：

1. `src/asset_based_agent/technical_platform/app.py`
   - 移除固定状态栏；
   - 使用 timeline/status controller；
   - 修复完成回调重复显示；
   - 修复 artifacts 的渲染顺序。
2. `src/asset_based_agent/technical_platform/store.py`
   - append 返回 message_id；
   - 增加 run/message 关联 API 和归属校验。
3. `src/asset_based_agent/technical_platform/local_migrations.py`
   - v14 schema；
   - run_message_links；
   - 安全历史迁移。
4. `src/asset_based_agent/technical_platform/conversation_timeline.py`
   - 新增时间线投影器。
5. `src/asset_based_agent/technical_platform/conversation_status.py`
   - 新增会话/轮次级状态控制器。
6. `src/asset_based_agent/technical_platform/agent_switch.py`
   - 保留现有增量合并；
   - 确保事件携带原始 session/operation 绑定。
7. `src/asset_based_agent/technical_platform/task_events.py`
   - 核查后台任务完成事件是否能提供 run/session/message 归属。
8. `src/asset_based_agent/technical_platform/session_service.py`
   - 核查会话切换、归档和恢复后时间线归属。
9. `src/asset_based_agent/technical_platform/project_catalog.py`
   - 核查 active store 切换后状态控制器是否重绑定。
10. `scripts/build_technical_platform.py`
    - 新模块使用动态导入时加入 hidden imports，确保 EXE 包含。

测试文件建议：

1. `tests/technical_platform/agent_rebuild/acceptance/test_app_wiring.py`
2. `tests/technical_platform/test_local_migrations.py`
3. 新增 `tests/technical_platform/test_conversation_timeline.py`
4. 新增 `tests/technical_platform/test_conversation_status.py`
5. 新增 `tests/technical_platform/test_run_message_links.py`

---

## 6. 测试先行要求

修改生产代码前先补充失败测试。不得通过删除旧测试、放宽断言或跳过测试完成施工。

### T1：回复只显示一次

- 输入“你好”；
- Agent 返回固定回复；
- transcript 中回复文本计数必须等于 1；
- composer 上方不存在重复 QLabel 文本。

### T2：运行状态进入对话

- 模拟 understanding → model streaming → completed；
- 状态卡显示在本轮用户消息之后；
- 完成后临时状态卡消失或转为最终事件；
- 输入框上方没有固定状态栏。

### T3：空会话提示

- 新建空会话；
- “添加本轮资料……”只出现在 transcript 空状态；
- 发送第一条消息后空状态消失。

### T4：成果归属稳定

- 第一轮执行生成任务并产生 3 个成果；
- 第二轮发送普通聊天消息；
- 3 个成果仍紧跟第一轮助手消息；
- 第二轮助手消息下没有成果；
- 重新打开应用后顺序不变。

### T5：跨会话隔离

- 会话 A 正在流式生成时切换到会话 B；
- A 的 live status、回复和成果不得出现在 B；
- A 完成后切回 A，内容正确显示且只出现一次。

### T6：旧数据迁移

- 从 v13 fixture 升级到 v14；
- 消息、runs、附件哈希不变；
- 可唯一推断的 run 标记 `legacy_inferred`；
- 不可推断 run 标记 `legacy_unlinked`；
- legacy_unlinked 不挂在最新回复下面；
- 重复迁移幂等。

### T7：组合任务与审核成果

- plan 多步骤成果全部绑定主任务完成消息；
- 审核报告、批注副本、生成文件仍可打开；
- 过程 JSON 不进入用户成果列表；
- 文件打开和打开所在目录链接保持有效。

### T8：取消与失败

- 取消只产生一条取消事件；
- 失败只产生一条可操作错误信息；
- 不得同时在 transcript 与固定 QLabel 重复显示；
- 失败轮次不展示旧成果。

---

## 7. 实机验收步骤

1. 使用本地账号登录；
2. 打开包含历史生成成果的会话；
3. 发送普通“你好”；
4. 确认回复只显示一次；
5. 确认旧 Word/PDF/PNG 未移动到“你好”的回复下面；
6. 执行一个可产生文件的本地 Skill；
7. 确认运行状态显示在本轮消息下方并原位更新；
8. 确认最终文件紧跟该轮完成回复；
9. 在任务执行期间切换到另一会话；
10. 确认另一会话没有旧状态、旧回复或旧成果；
11. 关闭并重新打开客户端，重复检查消息与成果顺序；
12. 验证文件链接仍可正常打开。

布局验收：

- transcript 与 composer 之间不存在固定状态栏；
- composer 不被状态文字顶动；
- footer 仅保留只读/计费类固定说明；
- 长回复不会遮挡输入框，也不会复制到输入框上方。

---

## 8. 回归命令

使用仓库既有虚拟环境，设置 `PYTHONPATH=src` 后至少运行：

```text
pytest tests/technical_platform/agent_rebuild/acceptance/test_app_wiring.py -q
pytest tests/technical_platform/test_conversation_timeline.py -q
pytest tests/technical_platform/test_conversation_status.py -q
pytest tests/technical_platform/test_run_message_links.py -q
pytest tests/technical_platform/test_local_migrations.py -q
pytest tests/technical_platform/agent_rebuild -q
```

完成后执行：

```text
python scripts/build_technical_platform.py
python scripts/smoke_technical_platform_exe.py
```

如果 Windows 中文路径参与测试，遵循仓库 `AGENTS.md`：使用 WSL/bash、Git Bash 或已落盘脚本，不用 PowerShell 传递中文路径或中文参数。

---

## 9. 验收门禁

只有满足以下全部条件才允许报告完成：

- 同一助手回复在 UI 中只出现一次；
- 输入框上方不再存在通用状态栏；
- 当前轮次运行状态显示在对话时间线中；
- 成果与对应消息建立稳定、可持久化的关联；
- 普通聊天不会带出历史成果；
- 会话切换期间没有跨会话状态、回复或成果污染；
- v13 → v14 迁移不丢消息、不丢 runs、不动原始附件；
- 现有文件打开、审核报告、批注、组合任务能力无回归；
- 自动化测试全绿；
- 新 EXE 冒烟通过。

任一门禁未通过时，必须保留失败测试、数据库快照或截图证据，明确报告阻塞，不得以“基本完成”代替验收。

---

## 10. 交付物

Kimi Work 最终必须提交：

1. 源码修改；
2. v14 数据迁移及测试；
3. 对话时间线与状态控制器测试；
4. 会话切换和成果归属实机截图；
5. 测试结果清单；
6. 新构建 EXE 路径与 SHA256；
7. Git commit（除非用户明确要求，否则不要推送远端）；
8. 实施账本，记录每阶段结果、失败证据和最终验收结论。

