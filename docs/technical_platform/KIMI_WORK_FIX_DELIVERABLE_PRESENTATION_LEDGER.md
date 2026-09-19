# Kimi Work 执行账本：只向用户交付最终生成文件（F00—F08）

> 工作文档：`D:/1/1/ai-excel-agent/docs/technical_platform/KIMI_WORK_FIX_FINAL_DELIVERABLE_PRESENTATION.md`
> 本账本按 F00—F08 逐阶段记录命令、测试与结果。

## 仓库位置判断（F00 前置）

工作文档第 1 节写"仓库：`D:/1/1/ai-excel-agent`"，判定为模板残留（与上一轮多期间修复文档相同写法）。实际施工仓库为 `D:\ZQ-Acceptance\local-feature-checkout`，依据：

- 交接文档 `docs/technical_platform/KIMI_CODE_HANDOFF.md` 明确 local-feature-checkout 为权威工作树；
- 问题运行目录来自 EXE 20260919-2235，该 EXE 从 local-feature-checkout（33d55d2）构建；
- `D:/1/1/ai-excel-agent` 停在 2026-06-09 的 cbc7d94，且有 863 个未提交用户改动（含删除 AGENTS.md），不施工、不覆盖；
- 两仓库同 origin，但关键文件全部有差异。

AGENTS.md 内容已从 `D:/1/1/ai-excel-agent` 的 HEAD（git show）读取：最高优先级为正式 Word 文档保护规则，本轮不涉及。

## F00：建立基线并保护现场

- 分支：`codex/local-platform-feature-update`
- HEAD：`d44358a Record reference-role fix and second candidate acceptance evidence`
- `git status --porcelain`：干净（无输出）
- Python 环境：`D:\1\1\ai-excel-agent\.venv\Scripts\python.exe`（既有约定），`QT_QPA_PLATFORM=offscreen`，PYTHONPATH=src
- 测试入口：`pytest tests/technical_platform tests/report_review_app tests/report_review_server -q --basetemp=D:/ZQ-Acceptance/tmp-pytest-basetemp -p no:cacheprovider`
  - 注意：根级 `tests/test_detail_*.py` 三个文件为既有收集错误（缺 test_detail_workbook_pipeline_guards 模块），不得跑 `pytest tests` 全目录
  - 上一轮基线：1662 passed / 0 failed
- `valuation-detail-workbook-fill/SKILL.md`（452 行）已完整阅读：交付门禁要求 `delivery_check_report.json`、`execution_scope.json` 等内部工件继续生成；封面 F7=主体、F9/H9/J9=年/月/日
- 未修改任何业务代码；未覆盖用户已有改动

### F00 调用链（生成结果 → 成果注册 → 步骤依赖 → UI 渲染 → 文件打开）

1. **结果装配**：`src/asset_based_agent/technical_platform/generation.py::_execute_generation` 391—407 行。成功时 `result['artifacts']` 登记 `detail_workbook.xlsx` + `completion_status.json` + `delivery_check_report.json` + `execution_scope.json` + `user_feedback.md`，每项仅 `{name, path, sha256}`；失败/取消仅登记 `user_feedback.md`。经 `store.save_result` 持久化到 `runs.result`。
2. **成果读取**：`store.run(run_id)['result']`；组合任务经 `step_results.py::StepResults.read`。
3. **步骤依赖解析**：`artifact_registry.py::resolve_step_inputs` 52—58 行，按 `expected_name`（`detail.generate`→`detail_workbook.xlsx`，`history.generate`→`history_fragment.docx`）过滤，要求恰好 1 项，并做路径边界 + 哈希校验。
4. **UI 渲染**：`app.py` 932—935 行（单任务 generation）遍历全部 artifacts 渲染"打开文件"；927—929 行（组合 plan 步骤成果）同样无差别渲染。
5. **文件打开**：`app.py` 1090—1092 → `generation.py::artifact_path`（按 index）；1062—1064 → `plan_results.py::step_artifact_path`（按 index）。
6. **其他消费方**：
   - `branch_context.py::validate_generated_files` 38—41 行：迭代全部 artifacts 校验 name/哈希（分支上下文引用校验）；
   - `browser_upload_candidates.py::_references` 12—14 行：全部 generation artifacts 成为网站上传候选；
   - `browser_upload_source.py::resolve_upload_source` 49—58 行：按 index 解析上传源；
   - `branch_understanding.py` 33 行：把 artifacts 的 name/sha256 摘要进模型上下文。

（后续阶段陆续追加）

## F01：新增最小失败测试

- 新测试文件：`tests/technical_platform/test_delivery_presentation.py`（24 个测试，覆盖 F01 全部 6 项 + F02/F04/F06 边界）
- 首次运行：模块缺失导致收集错误（预期）；随后用 `f01_repro.py` 直接以真实代码路径复现当前行为：
  - `打开文件` 链接数 = 5；`completion_status.json`/`delivery_check_report.json`/`execution_scope.json`/`user_feedback.md` 全部可见；无"最终文件"字样 —— 用户可见错误稳定复现
- 契约模块实现后首跑：22 passed / 2 failed，失败的恰为两个 UI 测试（真实行为失败），符合"先失败"要求
- 修复后：24 passed

## F02：成果角色模型

- 新模块：`src/asset_based_agent/technical_platform/artifact_contract.py`
- 字段：`role`（`primary`/`validation_evidence`）、`visibility`（`user`/`internal`）、`display_name`（可选，安全校验：非路径、无非法字符、≤120 字符）
- 不完整或未知声明一律 `ValueError` 拒绝；`role==primary` 与 `visibility==user` 强一致
- 旧结果兼容：无声明字段时按标准名推断（`detail_workbook.xlsx`/`history_fragment.docx`/`financial_brief.*`/`office_workflow_contract_validation.json` 为 primary/user；其余一律 internal，不认识的旧文件不会当成业务交付物）
- 哈希、目录边界、session/run 授权校验未改动

## F03：generation 结果登记

- `generation.py` 新增 `register_artifacts()`：登记时逐项打 role/visibility/display_name
- `detail_workbook.xlsx` 为唯一主交付物；`completion_status.json`/`delivery_check_report.json`/`execution_scope.json`/`user_feedback.md` 登记为内部证据
- 失败/取消仍只登记 `user_feedback.md`（内部）；`detail_workbook_staging.xlsx` 不在登记名单且即使出现也推断为 internal
- 发布前门禁：文件存在 + 位于授权输出目录（`is_relative_to(work)`）+ 登记哈希 + worker status.json ok；验收门禁（delivery_check pass 才发布 detail_workbook.xlsx）由 Skill 管线 `publish_after_review` 强制（失败抛 ReviewBlocked，worker ok=False，Harness 不发布 Excel）——已核实源码

## F04：Artifact Registry 与组合任务兼容

- `artifact_registry.py::resolve_step_inputs` 改用 `select_primary(result, expected_name)`：按主交付物身份（name + role==primary）解析，旧结果按标准名推断兼容
- 主交付物缺失/多个 → `ValueError` 明确失败；声明为 evidence 的同名文件不得作为业务输入
- 路径边界 + 哈希校验保持不变

## F05：Agent 回复和 UI 展示

- `app.py::render_messages` generation 分支：只遍历 `user_artifacts(result)`；单一主交付物且成功时显示"{label}已生成并通过校验。"+"最终文件：{display_name} [打开文件] [打开所在文件夹]"；多交付物（财务简表 docx/pdf/png）逐行显示 display_name
- 声明元数据非法时显示"生成成果记录校验失败"而非崩溃
- 组合步骤成果（plan 分支）同样只渲染用户可见工件
- 新增链接 scheme `zq-artifact-folder:{run}/{index}`，复用 `artifact_path` 授权/哈希校验后打开所在文件夹
- 失败/取消结果无可见工件链接（user_feedback.md 为 internal）
- `branch_understanding.py` 摘要增加 role/visibility/display_name 字段，Agent 可指出唯一最终文件
- 范围决策：`browser_upload_candidates.py` 本轮不改（文档第 4.2 节限定"正常成功对话"；上传流程有独立逐对象确认，且既有上传测试使用非标准名夹具）

## F06：用户显示名

- `artifact_contract.detail_display_name(work)`：从 `output/cover_fill_report.json`（status=='pass' 的确定性封面填报记录）取 F7 主体 + F9/H9/J9 年月日，生成 `{主体}评估明细表（YYYY-MM-DD）.xlsx`
- 清理 Windows 非法字符与控制字符、去空白、主体 ≤60 字符、全长 ≤120 字符；缺主体/缺日期/非法日期/类型错误/门禁未过/文件缺失 → 退化 `最终评估明细表.xlsx`
- 不修改内部标准文件名，display_name 不参与任何路径解析（测试 `test_display_name_never_drives_resolution` 证明）
