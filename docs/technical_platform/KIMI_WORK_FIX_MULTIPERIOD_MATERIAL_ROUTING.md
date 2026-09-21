# Kimi Work 修复任务：多期间财务资料导致评估明细表生成失败

> 可直接执行的专项修复文件  
> 制定日期：2026-09-19（Asia/Shanghai）  
> 权威工作树：`D:\ZQ-Acceptance\local-feature-checkout`  
> 分支：`codex/local-platform-feature-update`  
> 制定时 HEAD：`5bf8444d61f14733f3d6f2cbf98946a21aa5b0f8`  
> 当前工作区：制定本文时干净  
> 范围：本地源码、测试和本机构建；不推送 GitHub、不部署 Zeabur、不激活 Release

---

## 0. 直接给 Kimi Work 的执行命令

请完整读取本文件，并按 F00→F07 顺序持续执行本次修复。每阶段必须遵循：

```text
核验现状 → 编写失败测试 → 确认红灯 → 最小实现 → 专项测试
→ 邻域回归 → 静态检查 → 记录证据 → 自动进入下一阶段
```

不要等待用户重复发送“继续”。不要先猜、不要只修改错误文案、不要删除现有安全门禁、不要通过忽略多余文件让测试表面通过。只有缺少账号、验证码、付费授权或必要外部环境时才报告阻塞；本专项原则上可以使用合成夹具完成全部代码验证。

一句话 Bug 定义：

> 当用户明确上传同一主体多个报告期的资产负债表用于生成评估明细表时，平台应按Skill规则从报表表头选择最新报告期作为主报表，并保留其他期间为参考；当前资料角色解析器却把第二份`balance_sheet`直接视为致命冲突，导致Harness将任务错误标记为执行失败。

---

## 1. 必读材料

开工前完整读取：

1. `docs/technical_platform/KIMI_CODE_HANDOFF.md`
2. `docs/technical_platform/AGENT_HARNESS_OPTIMIZATION_PLAN_CC_HAHA.md`
3. `.codex/skills/valuation-detail-workbook-fill/SKILL.md`
4. `.codex/skills/valuation-detail-workbook-fill/references/scope_first_execution.md`
5. `src/asset_based_agent/technical_platform/material_analysis.py`
6. `src/asset_based_agent/technical_platform/generation.py`
7. `src/asset_based_agent/technical_platform/generation_worker.py`
8. `src/asset_based_agent/technical_platform/harness.py`
9. `src/asset_based_agent/technical_platform/tool_dispatcher.py`
10. `src/asset_based_agent/technical_platform/event_store.py`
11. `src/asset_based_agent/technical_platform/conversation_state.py`
12. `src/asset_based_agent/technical_platform/workflow_events.py`
13. `src/asset_based_agent/report_review_server/services/material_analysis.py`
14. `tests/technical_platform/test_material_analysis.py`
15. `tests/report_review_server/test_material_analysis.py`

若文件在开工后已有新改动，先比较当前代码与本文，不得覆盖其他开发成果。

---

## 2. 已确认的现场证据

### 2.1 失败任务

- 任务编号：`b08511b958f74dbd9913270c390bf0e4`
- 真实任务数据库：
  `D:\ZQ-Acceptance\real-machine-test\20260919-dialogfix\data10\platform.sqlite`
- 开始：2026-09-19 09:06:11 UTC
- 失败：2026-09-19 09:06:23 UTC
- 任务状态：`failed`
- 步骤：`execute`
- 工具：`detail.generate`
- Skill：`valuation-detail-workbook-fill 0.2.0`
- 异常：`ValueError`
- 用户可见原因：`存在多份同类资料，需要先确认本轮使用的主体和期间`

数据库只允许只读诊断，不得修改、迁移或用作测试写库。

### 2.2 本轮文件范围

任务正确冻结了五个文件及SHA256：

1. 2026年6月资产负债表
2. 银行账户余额表
3. 2025年12月资产负债表
4. 2026年6月银行流水
5. 2024年12月资产负债表

三个资产负债表属于同一企业、不同报告期。用户请求是根据本轮上传资料生成该公司的评估明细表。

### 2.3 已排除的错误方向

- Agent没有选错Skill：计划明确选择`valuation-detail-workbook-fill`。
- 当前轮附件没有串入历史文件：五个输入均来自本轮冻结范围。
- 文件哈希门禁没有失败。
- 不是Office/WPS执行失败：尚未进入生成子进程。
- 不是模板写入失败：尚未复制和填报正式模板。
- 不是模型JSON截断：服务端资料识别已返回可被本地解析的计划。
- 不是Skill禁止多期间：Skill明确要求同一主体多期间时选择最新报告日期。

### 2.4 根因代码

`material_analysis.resolve_roles()`当前使用`dict[role] = file_id`，任何第二个非`other`同类角色都立即抛错。

现有测试`test_analysis_rejects_unknown_file_and_ambiguous_role`还把“两份balance_sheet必须报错”锁定为预期行为。

`generation.py`只有在`provider.analyze()`完整返回后才保存`material_analysis.json`。本次在角色解析阶段抛错，因此模型原始识别结果没有作为Artifact持久化。

`harness.py`将`ValueError`统一映射为`failed`，没有把可澄清的资料歧义转换成`node_waiting_user`/会话问题。

`generation_worker.detail()`目前只接受单个`balance_sheet`，虽然Skill契约已经声明任务配置可以接受`financial_statements`列表。

---

## 3. 故障归属

### 主要责任：Harness执行集成/资料适配层

具体是：

1. 角色模型只能表达“一种角色一个文件”。
2. 没有执行Skill规定的同主体多期间选期规则。
3. 可澄清歧义被当成执行失败。
4. 失败前没有持久化资料识别Artifact。

### 次要责任：Agent计划粒度不足

本次计划中`target_inputs`和`reference_inputs`为空，所有文件被平铺到`inputs`。Agent没有明确表达：

- 2026年6月报表是当前期目标；
- 2024、2025年报表是历史参考；
- 银行流水是银行资产证据；
- 银行账户余额表需要独立识别是否属于可用对账证据。

### 不应修改为“修Skill”

Skill规则本身正确。禁止删除或弱化以下规则：

- 同一主体多期间选择最新报告日期；
- 不使用文件修改时间决定期间；
- 不仅依赖文件名；
- 主体冲突或日期缺失时停止并明确说明；
- 原件只读、模板锁定、公式和链接保护。

---

## 4. 目标行为

### 4.1 同一主体、多期间

从用户明确选中的资产负债表原件表头，确定性提取：

- 编制主体；
- 报告日期；
- 来源文件ID和SHA256。

若主体相同：

- 报告日期最新的一份成为`balance_sheet`；
- 全部同主体报表按日期排序保存为`financial_statements`；
- 其余期间属于历史参考，不得覆盖当前期金额；
- 不询问用户，不失败。

本次现场期望：自动选择2026年6月报表，2024、2025年报表作为历史参考。

### 4.2 真正需要澄清的情况

以下情况不得静默选择：

- 多个不同主体；
- 报表主体无法从表头确认；
- 报告日期无法从表头确认；
- 同一主体、同一报告日期存在两份内容不同的候选主报表；
- 用户明确指定的期间与资料识别出的最新期间冲突；
- 其他单值角色存在无法安全合并的多个候选文件。

这些情况进入`waiting_user/needs_input`，在原会话提出结构化选择题；不得把任务标记为普通执行失败。

### 4.3 澄清后继续

- 保留原TurnEnvelope、文件版本、模型识别计划和任务身份。
- 用户回答后从资料范围决策节点继续。
- 不重新上传原始文件。
- 不重新调用已经成功完成的资料识别模型。
- 不创建第二次计费请求。
- 如果任务架构暂时不能安全恢复原run，必须先实现可验证的续跑契约，不能靠重新提交整个任务规避。

---

## 5. 设计约束

### 5.1 不信任模型决定主体和日期

服务端模型继续只负责文件用途分类。主体和日期必须从用户明确选择的原始Excel可见表头中本地确定性提取，并记录来源位置。

允许复用或抽取`generation_worker._financial_metadata()`的逻辑，但不要让资料分析层反向依赖子进程入口。推荐提取为可测试的共享模块，例如：

`src/asset_based_agent/technical_platform/financial_statement_metadata.py`

### 5.2 建议的结构化结果

不要继续返回只有`dict[str, file_id]`的结果。可采用等价的强类型结构：

```text
MaterialResolution
  primary_roles: dict[str, file_id]
  grouped_roles: dict[str, list[file_id]]
  financial_statements: list[
    file_id / entity / reporting_date / sha256 / evidence
  ]
  reference_file_ids: list[file_id]
  unresolved: list[MaterialAmbiguity]
  raw_plan
```

具体类型名称可以调整，但必须表达“一类多文件”“主文件”“参考文件”和“待澄清问题”。

### 5.3 生成输入契约

`generation.py`生成的`job.json`对评估明细表至少支持：

```json
{
  "balance_sheet": "inputs/balance_sheet.xlsx",
  "financial_statements": [
    "inputs/financial_statement_001.xlsx",
    "inputs/financial_statement_002.xlsx",
    "inputs/financial_statement_003.xlsx"
  ]
}
```

要求：

- 使用ASCII staging文件名；
- 每个副本重新校验SHA256；
- `balance_sheet`必须指向最新期间原件的副本；
- `financial_statements`保持可审计顺序；
- `generation_worker.detail()`将正确的原始当前期报表传给`--financial-statement`；
- 不扫描输入目录寻找“看起来更新”的文件；
- 不使用文件修改时间。

### 5.4 Artifact先于解析失败

模型计划返回并通过基本ID/schema校验后，立即持久化脱敏的`material_analysis.json`或等价Artifact，然后再执行角色归并和期间决策。

Artifact至少包含：

- request/run ID；
- 每个file_id的分类、理由；
- 不包含本地绝对路径和隐藏表正文；
- 主体/日期本地提取结果；
- 主报表选择结果或澄清原因；
-规则/Skill版本和文件SHA256。

### 5.5 安全边界不变

- 不上传原始二进制和本地路径。
- hidden/veryHidden内容不得进入模型上下文。
- 原件只读。
- 只处理TurnEnvelope明确选中的文件。
- 不修改锁定模板。
- 不因为多期间支持而扩大目录扫描范围。

---

## 6. F00—F07 施工步骤

### F00：冻结基线与建立修复账本

执行：

```text
git branch --show-current
git rev-parse HEAD
git status --short
git diff --stat
```

创建：

`docs/technical_platform/KIMI_WORK_FIX_MULTIPERIOD_MATERIAL_ROUTING_LEDGER.md`

记录当前HEAD、dirty状态、既有测试基线和所有后续证据。不得重置或清理他人改动。

### F01：测试先行，稳定复现

先修改现有错误测试，不允许仅删除断言。新增最小合成XLSX夹具，表头包含主体和报告日期。

至少新增以下红灯测试：

1. `test_same_entity_multi_period_selects_latest_balance_sheet`
2. `test_previous_period_statements_are_preserved_as_references`
3. `test_conflicting_entities_require_clarification`
4. `test_missing_reporting_date_requires_clarification`
5. `test_same_entity_same_date_different_files_require_clarification`
6. `test_material_plan_is_persisted_before_role_resolution`
7. `test_generation_job_contains_ordered_financial_statements`
8. `test_clarification_does_not_start_generation_worker`
9. `test_clarification_resume_reuses_material_analysis`
10. `test_single_balance_sheet_route_remains_compatible`

先运行并把预期失败记录到账本。不得使用真实客户文件作为唯一测试夹具。

### F02：实现确定性报表元数据与多期间选择

实施：

- 提取共享的资产负债表表头元数据读取器。
- 只读取可见表头必要区域。
- 返回主体、报告日期和证据单元格。
- 对同主体多期间排序并选择最新。
- 对冲突返回强类型歧义，不抛普通`ValueError`。
- 保留未知/重复file_id、遗漏文件、非法角色等安全校验。

验收：F01前五项转绿；文件名和mtime变化不影响选择结果。

### F03：扩展生成输入和Worker

实施：

- `generation.py`复制主报表和全部同主体财务报表到ASCII staging。
- `job.json`增加`financial_statements`列表。
- `generation_worker.detail()`校验并使用该列表。
- 当前期原件作为`--financial-statement`，避免封面主体/日期从归一化文件丢失。
- 旧单报表任务保持兼容。

验收：F01第7、10项转绿；模板、原件和所有输入SHA256保持不变。

### F04：把可澄清歧义接入Agent/Harness会话状态

实施前先复用现有`conversation_state`、`node_waiting_user`和统一事件结构，不另造不兼容状态。

要求：

- 使用明确的领域异常或结果类型，例如`MaterialClarificationRequired`。
- 生成结构化问题：候选主体、期间、文件显示名、选择影响。
- Harness不得把它归为`failed`或`unknown`。
- 对话显示等待用户，停止按钮仍可用。
- 用户回答必须绑定原task、question/revision和候选文件版本。
- 回答过期、文件变化或跨会话回答必须拒绝。
- 恢复时不重复模型资料识别和计费。

验收：F01第8、9项转绿，并增加取消、过期回答和文件变化非回归测试。

### F05：补齐诊断Artifact与可观测性

实施：

- 在角色归并前保存模型分类结果。
- 记录本地主体/日期选择报告。
- 失败、澄清和成功均有可读取Artifact。
- 用户提示区分：资料识别失败、需要选择、生成失败、Office兼容失败。
- 不再统一显示“请检查模型服务连接”。本次模型服务已成功返回，该提示会误导用户。

验收：F01第6项转绿；诊断文件不含绝对路径、隐藏内容、API Key、Token或费用。

### F06：真实场景只读复测

先使用合成同主体三期报表完成端到端测试，再对现场任务文件进行只读复测。现场资料路径来自任务快照，不得修改原件。

现场期望：

- 自动选择2026年6月资产负债表；
- 2024、2025年报表登记为历史参考；
- 银行流水按实际表头识别；
- 银行账户余额表按实际内容归类，不强行当银行流水；
- 进入本地生成与校验，而不是停在资料识别；
- 如果生成链另有真实业务门禁，必须报告新的独立根因，不能与本问题混在一起。

若复测会调用付费模型，必须使用已有授权账号和费用上限；没有明确授权时改用固定的合成服务端响应完成本地验收，并把真实付费复测标记为阻塞。

### F07：完整回归与本机候选构建

运行：

```bat
set PYTHONPATH=src
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\technical_platform\test_material_analysis.py -q
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_server\test_material_analysis.py -q
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\technical_platform -q
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_app -q
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_server -q
```

对全部修改文件运行：

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m ruff check <修改文件>
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m mypy <本次核心模块>
git diff --check
```

验证通过后构建新的D盘本地验收EXE，不覆盖旧包：

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\build_technical_platform.py
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\smoke_technical_platform_exe.py
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\prove_local_builtin_skills.py
```

没有用户明确授权时，不提交、不推送、不部署、不创建Release。

---

## 7. 不允许的伪修复

以下方案一律拒绝：

- 看到多份资产负债表就固定选择列表第一项或最后一项。
- 根据文件名中的2024/2025/2026直接决定正式期间。
- 根据文件修改时间选择最新文件。
- 把多余报表全部标成`other`以绕过重复角色。
- 只把`ValueError`文案改得更友好。
- 捕获异常后仍重新提交整个任务。
- 删除现有重复角色测试但不增加新行为测试。
- 把三个期间金额混合填入同一当前期评估明细表。
- 修改Skill规则，使其只允许单份资产负债表。
- 跳过主体、日期和SHA256核对。
- 为了复测直接改动现场原始Excel。

---

## 8. 回归风险重点

修复后重点检查：

1. 单资产负债表项目仍正常。
2. 简单银行资产轻量模式仍正常。
3. 只有资产负债表、没有科目余额表/序时账时不被机械拒绝。
4. 多主体不会被错误合并。
5. 历史期间不会覆盖当前期封面日期和账面金额。
6. 财务简报三期排序逻辑不被本次抽取共享代码误伤。
7. 报告审核Skill不使用本生成任务的选期规则。
8. hidden/veryHidden过滤不回退。
9. 澄清恢复不会重复扣费。
10. 取消任务不会在用户回答后重新启动。
11. 锁定模板哈希、公式和链接保持不变。
12. 失败任务仍有足够Artifact进行诊断。

---

## 9. 验收门槛

全部满足才算修复完成：

| 项目 | 目标 |
|---|---:|
| 同主体三期报表自动选择最新期间 | 通过 |
| 历史期间保留为参考且不覆盖当前期 | 通过 |
| 多主体/缺日期进入结构化澄清 | 通过 |
| 可澄清情况被标记为执行失败 | 0 |
| 澄清后重复资料识别模型调用 | 0 |
| 澄清后重复扣费 | 0 |
| 未选历史附件进入任务 | 0 |
| 隐藏表内容进入模型上下文 | 0 |
| 原始文件被修改 | 0 |
| 模型识别结果无Artifact | 0 |
| 单报表及既有轻量流程回归 | 全部通过 |
| 技术平台、客户端、服务端相关测试 | 全部通过 |
| Ruff、限定Mypy、diff-check | 通过 |
| 新本机EXE冒烟 | 通过 |

---

## 10. 最终汇报格式

```text
结论：已修复 / 尚未修复

根因确认：
- Skill：...
- Agent：...
- Harness/适配层：...

修改文件：...
新增或修改测试：...
红灯证据：...
绿灯证据：...
真实场景复测：...
是否发生付费调用：...
是否生成新EXE：绝对路径、大小、SHA256
未完成项或阻塞：...
Git状态：...
是否推送/部署：否（除非另有明确授权）
```

Kimi Work不得在没有运行证据时写“已完成”，也不得把“进入生成阶段”当成最终Excel已通过业务验收。
