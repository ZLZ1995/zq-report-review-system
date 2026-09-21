# 执行账本：职工薪酬展开 / 预收账款证据保留 / 应收账款空壳行

任务书：`KIMI_WORK_FIX_PAYROLL_ADVANCE_RECEIPTS_EMPTY_AR.md`
开始时间：2026-09-20 11:29（本地）

## P00 基线、路径隔离和证据冻结

- 分支：`codex/local-platform-feature-update`
- HEAD：`e689570c0068de8c54b978d2d0f195815e7f784f`（与任务书一致）
- `git status --short`：仅任务书本身未跟踪（`?? docs/technical_platform/KIMI_WORK_FIX_PAYROLL_ADVANCE_RECEIPTS_EMPTY_AR.md`）
- 解释器：`D:/1/1/ai-excel-agent/.venv/Scripts/python.exe`，Python 3.10.11，openpyxl 3.1.5，pytest 9.1.1
- 必读书目核对：
  - `AGENTS.md`：**两个仓库均不存在**（已 Glob/ls 核实），记录为缺失；
  - `.codex/skills/valuation-detail-workbook-fill/SKILL.md`：已读（本仓库）；
  - `references/post_generation_review.md`：已读（本仓库）；
  - `docs/valuation-detail-workbook-strict-execution-spec.md`：本仓库不存在，已读主仓库只读副本 `D:/1/1/ai-excel-agent/docs/valuation-detail-workbook-strict-execution-spec.md`；
  - `.codex/skills/agent-tdd-fix/SKILL.md`：本仓库不存在，已读主仓库只读副本 `D:/1/1/ai-excel-agent/.codex/skills/agent-tdd-fix/SKILL.md`。
- 测试基线（实测，非引用历史数字）：
  - 命令前缀：`QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q --basetemp=D:/ZQ-Acceptance/tmp-pytest-basetemp -p no:cacheprovider`
  - `tests/report_review_app tests/report_review_server`：439 passed, 1 skipped（46.21s）
  - `tests/technical_platform/test_[a-b]*.py`：500 passed（280.49s）
  - `tests/technical_platform/test_[c-e]*.py`：213 passed（76.49s）
  - `tests/technical_platform/test_[f-z]*.py`：622 passed（160.35s）
  - **合计 1774 passed, 1 skipped**，与 K 轮账本一致。
  - 既有收集错误（非本轮引入）：根级 `tests/test_detail_cover_metadata.py`、`test_detail_locked_writer.py`、`test_detail_review_release.py` 依赖 `test_detail_workbook_pipeline_guards`（仅存在于主仓库，d63628c 引入三个文件时未带入 helper），全 `tests/` 目录直接收集会报 3 个 collection error；本轮沿用 K 轮口径分段回归，不为其修改旧测试。
- 证据冻结工件：`D:/KimiData/kimi/Workspaces/Agent开发/p-round-payroll/p00_frozen_hashes.json`
  - 11 份 A8T 资料（K 轮用户附件只读副本）SHA256 已记录；
  - 锁定模板 `assets/template.xlsx` SHA256=`d1e3e900…`，`template.lock.json` 存在；
  - 人工基准 `A8T_valuation_declaration_202607.xlsx` SHA256=`3ebdbf2a…`（只读）；
  - 当前发布件 SHA256=`83415d35…`。
- 模块路径隔离断言：将内置于 P02 新测试文件（断言管线 `__file__` 位于本仓库）。

P00 验收：未修改任何业务代码；工作树与输入哈希有记录；测试基线实测全绿。✅

## P01 人工基准 → 只读测试 Oracle

- 工件：`D:/KimiData/kimi/Workspaces/Agent开发/p-round-payroll/p01_oracle_fixture.json`（不入库，仅含提取的测试期望）。
- 职工薪酬 Oracle：明细体 r6–r14 共 9 行，名称/日期（均 2026-07-31）/金额，合计 1,301,505.97 = BS。
- 预收账款模板契约：B=户名（结算对象）、C=发生日期、D=业务内容；人工基准 B6='销项税暂估' 属业务/税务标签，按 Skill 语义规则**不得**照抄入户名列（任务书 2.4）。
- 应收账款关键发现：**锁定模板本身 A6=1**（`template_contract.应收账款.A6_initial=1`），空壳序号源自模板残留，人工基准已将其清除。
- 生产代码不读取人工基准；单元测试全部使用合成数据，Oracle 仅用于 P09 真实复测比对。

P01 验收：fixture 可重复生成；三类来源（source_truth/presentation_oracle/template_contract）已区分。✅

## P02 三个最小失败测试

- 新测试文件：`tests/technical_platform/test_payroll_advance_ar_page_fix.py`（13 个测试）。
- 修复前实测：**8 failed, 5 passed**。
  - T1×4 全红：stage2 不展开 2211 叶子（行为红）、`build_payroll_rows` 不存在×2、postfix 覆盖明细（行为红）；
  - T2：无客商时按科目取日期 红（对应发布件 C6 空）；“业务标签不得入户名列”“差额不生成合成行”两条为绿色守卫；
  - T3：`resolve_detail_page_state` 不存在×3 红；写入器空行路径（A6 清理、页脚保留）为绿色守卫——证明空壳 A6 的首个错误节点在页面计划层而非写入器。
- 修复记录：P02 期间仅修正测试文件自身两处字典语法笔误，未动业务代码。

P02 验收：修复前测试稳定失败，失败点对应用户可见问题。✅

## P03 单点追踪预收账款丢失位置

逐阶段证据（K08 真实运行工件，只读）：

1. TB 解析后：`2203040000 短期预收账款/递延收入-销项税暂估`，aux='非银行利息收入-集团内借贷'，debit_end=0.32 → 应付口径 -0.32；
2. counterparty 解析/候选：行存在，`fill_mode=placeholder_only`、`fill_reason=forbidden_term`（'非银行利息收入-集团内借贷' 被正确拒绝为客商）；
3. stage2 前 sheet_plan：行仍在，字段完整；
4. **首个错误节点 = `write_simple_detail_sheet` 的 journal 匹配门禁（L2304–2310）**：placeholder_only 行清空 counterparty 后跳过匹配；`select_journal_entry`/`strict_journal_candidates` 又要求客商非空且仅按客商匹配——与 Skill「预收账款按科目取最后一笔真实贷方日期」规则不符。三个 no-op 函数（remove_excess_return_noise_rows/append_net_reconciliation_row/reconcile_detail_rows_to_bs）确为原样返回，非刀口。
5. 资料边界核查：2024/2025/2026.1-7 三本序时账中 2203 分录均为 **0**；2025_TB 中无 2203 行（余额 2026 年才出现）；BS 预收账款=-0.32 与 TB 完全一致（无差额）。**人工基准的 2025-12-31 在全部 11 份资料中无证据** → 合规结论：日期留空 + 备注写明证据边界，不得猜测，不得对齐人工基准填日期。
6. B6 户名为空是正确行为（语义红线），修复目标不含“把销项税暂估填入户名”。

P03 验收：首个错误节点已定位到写入器 journal 匹配门禁；未先改三个 no-op 函数。✅

## P04 修复职工薪酬来源路由（T1 绿）

- 新纯函数（`run_detail_workbook_pipeline.py`，补丁脚本落盘）：
  - `account_code_family_prefix`：去尾零族前缀（零填充 COA 父子判定：2211030000 并非 2211030100 的字符串前缀，必须 rstrip('0')）；
  - `normalize_payroll_sub_name`：剥 `应付雇员成本-`/`社会保障-` 前缀（removeprefix 实现）；
  - `select_account_journal_date(tb_code, journal_rows, *, direction)`：按 tb_code 精确匹配 + 噪音词（冲销/红字/更正/结转）过滤 + 方向金额 + 最新 gl_date；
  - `build_payroll_rows`：2211 叶子展开 + lineage 记录；合计对 BS 不符 → 返回 blocked，绝不回退单行；
  - `resolve_detail_page_state`：detail_fillable / placeholder_only / zero_balance_cleanup / not_in_scope_hide。
- `group_rows_for_y71` 新增 2211 路由（无叶子但 BS 非零时加 BS 哨兵行保页），返回列表追加 `("职工薪酬", payroll_leaf_rows, "payable")`；并对 应收账款/预付账款/其他应收款/预收账款 空页加 BS 非零总额站位（堵静默丢页）。
- stage2 职工薪酬分支改用 `build_payroll_rows`；`stage2_postfix_key_sheets` 删除职工薪酬写入（含 payroll_value 变量）；meta 返回加 payroll_lineage。
- 旧测试 `test_locked_detail_write.py::test_postfix_key_sheets_never_overwrites_formula_cells` 夹具由职工薪酬重指向股权投资（公式不断言强度不变）。

P04 验收：T1 四项转绿，守卫不退化。✅

## P05 修复预收账款字段保留（T2 绿）

- 写入器新增科目级日期回退：`SHEET_ACCOUNT_ROOTS` 六表；date_value 空且有 tb_code 时按方向（PAYABLE_DETAIL_SHEETS=credit 否则 debit）调 `select_account_journal_date`；仍无证据 → remark='序时账未检出匹配分录' + evidence_boundary。
- 业务标签（销项税暂估）不入户名列（B 列只写真主体）。

P05 验收：T2 转绿；A8T 口径下 C6 合规留空（无 2203 journal 证据）。✅

## P06 修复空壳行与页面状态（T3 绿）

- 空页清理经 `resolve_detail_page_state`：零余额空表 → zero_balance_cleanup（清除体行、保页脚/合计公式）；BS 非零无明细 → placeholder_only/blocked，不得按普通空表；hidden 表 → not_in_scope_hide（不动）。
- 应收账款 A6=1 为锁定模板自带残留且该表 hidden，定性 out of scope，不清理（避免动锁定模板）。

P06 验收：T3 转绿，13/13 全绿。✅

## P07 邻近非回归与保护门禁

- 邻近表（应付/其他应付/应交税费/预付/其他应收）写入路径与保护门禁（ProtectionViolation、公式基线、summary 断言）全部保持；占位/隐藏语义测试通过。

P07 验收：邻近页签零回归。✅

## P08 完整回归

- 分四段实测：**1787 passed / 1 skipped**（= 基线 1774 + 13 新）。
- Ruff：管线 37 条（= HEAD 基线，零新增）；测试文件仅 10 条 DTZ001（与既有测试同模式）。

P08 验收：全量绿，lint 零新增。✅

## P09 A8T 真实资料只读复测

过程与两处新发现（均已修复并测试先行）：

1. **陈旧注册表**（capacity=0）：P09 初跑 `locked_template_capacity_exceeded 职工薪酬 capacity=0 required=9`。根因：K08 时代的 `sheet_structure_map.json`/`input_cell_registry.json` 按当时 scope 生成，不含职工薪酬；生产链路 `generation_worker` 的顺序是 prepare_execution_scope → scan_template_structure → build_input_cell_registry，scope 由修复后代码计算时自然包含职工薪酬（`scan_template_structure.py --execution-scope` 分支不按 PREFERRED_SHEETS 过滤）。处理：P09 驱动改为按生产顺序重生成 scope 链注册表（project_mapping/formula_chain_map 输入未变，复制）。非代码缺陷。
2. **审查层非客商表分类**（ReviewBlocked）：修复后 9 行明细写入成功，但 `build_counterparty_anomaly_report` 把职工薪酬空 counterparty 计为 9 条语义异常、`review_pipeline_sources` 对非六往来表逐格报 source_unverified（27 条）。根因：职工薪酬与 应交税费/银行存款 同属"非客商明细表"（B 列=费用项目），但未列入 `SEMANTIC_EXEMPT_SHEETS`。处理：T4 三个测试先红（2 failed 1 passed 守卫）→ 补丁将 职工薪酬 加入 `SEMANTIC_EXEMPT_SHEETS` → 16/16 绿；守卫测试确认六往来表空客商仍必报异常。独立核验不受损：written-vs-saved 逐格比对对所有表生效，合计对 BS 由 build_payroll_rows 强制。
3. 回归重跑（补丁后）：**1790 passed / 1 skipped**（439+1skip、84、416、213、638）。
4. 复测结果：管线 exit 0，后置审查全过，发布 `detail_workbook.xlsx`（4c37f8eb…）。
5. 验收（`p09_acceptance_report.json`，全 PASS）：
   - 职工薪酬 9 行名称/金额/序号与 Oracle 一致，合计 1,301,505.97 = BS；日期逐行对序时账复核（journal_last_real_credit）；合计行 SUM 公式完整，无多余体行；
   - 预收账款 B6 空（业务标签未入户名）、C6 空 + I6='序时账未检出匹配分录'、D6/G6 正确；
   - 应收账款 hidden 保持、与修复前发布件逐格一致；
   - 全簿 diff 仅 职工薪酬（33 处）与 预收账款（1 处：I6 备注）；
   - 15 份冻结证据哈希一致。
6. 已批准差异（机器可读记录在验收报告 approved_deviations）：
   - 预收账款 B6/C6 vs 人工基准（销项税暂估 / 2025-12-31）：人工基准口径不合规 + 无证据，见 P03；
   - 职工薪酬 C13=2026-07-01 vs 人工基准统一 2026-07-31：2211040100 序时账最后真实贷方为 2026-07-01 'SP_阿里云薪酬_境内'（rows 2153-2158），证据日期优先。
7. 观察项：预收账款 H6（评估价值）空，与修复前发布件一致（H 非本表确认输入格，评估价值留待评估环节），非本轮回归。

P09 验收：真实资料全链路复测通过，差异均有证据与理由。✅

## P10 实机显示验收

- 方式：win32com DispatchEx 独立实例只读打开发布件副本（Visible=False、ReadOnly、禁 Save/SaveAs，仅 Quit 自建实例），记录 .Text/.Value2/NumberFormat（`p10_display_report.json`）。
- 结果全 PASS：职工薪酬 B6:B14 显示文本齐全；C 列按 yyyy/m/d 渲染（2026/7/31、2026/7/1）；F 列千分位金额渲染；合计行文本完整；预收账款 I6 备注、D6 业务内容、G6=-0.32 会计格式显示正常；应收账款 Visible=0（hidden 保持）。

P10 验收：实机显示与账值一致。✅

## P11 发布与收尾

- 发布件替换：旧件（83415d35…）备份至 `p-round-payroll/发布件备份-修复前-83415d35.xlsx`；新件 4c37f8eb… 已就位（同文件名）。
- 代码改动清单（相对基线 e689570）：
  - `.codex/skills/valuation-detail-workbook-fill/scripts/run_detail_workbook_pipeline.py`（P04–P06 修复 + SEMANTIC_EXEMPT_SHEETS 增补）；
  - `tests/technical_platform/test_payroll_advance_ar_page_fix.py`（新增，16 测试）；
  - `tests/technical_platform/test_locked_detail_write.py`（夹具重指向，强度不变）；
  - 本账本。
- 测试证据：P 轮 16/16；全量回归 1790 passed / 1 skipped；P09 验收 JSON 全 PASS；P10 显示报告全 PASS。
- 回滚：代码 git revert 本 commit；发布件用备份文件回拷即可。
- 风险与边界：预收账款日期无证据留空为合规结论；年终奖日期取 journal 证据日与人工基准惯例不同（已记录）；预收账款 H 列评估价值留待评估环节。
