---
name: valuation-detail-workbook-fill
description: Build or update a Chinese asset-based valuation detail workbook and declaration workbook from a balance sheet, subject-balance workbook, and optional journals or detailed ledgers. Use when Codex needs to produce a 评估申报表/评估明细表 through a balance-sheet-driven scoped workflow, including a lightweight single-asset route, detail-page filling only for non-zero accounts, controlled placeholder handling, formula/link preservation, and later incremental replacement when supplementary detail files arrive.
---

# Valuation Detail Workbook Fill

## 锁定模板约束（平台接入）

- 使用用户确认的固定模板，运行时不允许更换模板；所有生成数据回填到该模板副本的合法输入区域。
- 模板原件不修改；保留模板样式、工作表结构、公式、链接和固定页脚，继续执行下述保护与交付门禁。
- 绑定缺失、模板哈希不符或布局不匹配时停止，不扫描旧项目产物充当模板。
- 平台通过本目录 `template.lock.json` 绑定 `assets/template.xlsx`，不得使用旧项目临时工作簿配置替代；缺少绑定或哈希校验失败时禁止生成。
- 平台接入先运行 `scripts/prepare_execution_scope.py`，然后按范围扫描模板输入区。当前银行对账单入口支持标准表头 XLSX；余额不一致或资料不足时阻断，不用报表金额替代对账单证据。用户要求原公式不可更改，因此平台不自动应用下文的可选公式保护改写。

### 模板占位与执行替换

- 用户允许模板使用待填占位，执行本 skill 时用本次来源资料替换；这不授权改动预设公式、跨表引用、超链接或模板结构。
- 文本输入格可使用 `【待填：字段名】`。金额、数量、日期、年限、税率等参与计算的输入格保持空白，并在任务的 `template_placeholder_map.json` 中记录位置、字段类型和需要的来源；不得写入文字导致类型错误，也不得用虚构的 0、1、日期或年限消除除零提示。该清单不属于已获验证的业务数据。
- 识别占位位置前核对实际表头、输入区域和公式依赖。不得把所有空格都视为可填区域；公式格、汇总页预设链接格、固定标签和页脚不属于占位替换目标。
- 空模板尚无输入时，可保留由空输入直接引发的 `#DIV/0!` 作为待填状态，不因此修改公式或阻止登记为待填模板；必须记录受影响位置及缺失输入。`#REF!`、公式丢失、链接改绑等结构错误不适用此例外。占位许可不替代正式模板哈希绑定和布局校验。
- 执行时仅在模板副本中逐项回填，每项记录 `sheet`、`cell`、`field_type`、来源文件及来源位置、处理状态；无资料的项目列入 `missing_materials.json`，不得猜填。现有 `placeholder_only` 是缺明细的业务状态，不能和模板文字占位符混为一谈。
- 正式发布前重新打开文件，检查待填标记残留、已填写字段的类型和来源、计算结果及链接保护。任何仍需使用的字段未替换、错误仍影响本轮计算或汇总，必须阻断正式发布；不能因它在模板阶段获准占位而跳过最终验收。不适用的占位只可清除合法输入格并记录理由，不得仅通过隐藏错误页使结果通过。
- 当前规则不要求为消除空模板提示而添加 `IFERROR` 或改写原公式。用户授权的缺资料占位流程继续遵守生成后复核与交付门禁。

## Core Goal

### 平台自动识别资料

用户无需手工分配资料角色。读取授权后，平台将本地提取的可见文本节选交由已登录的模型服务识别，再通过本地确定性校验选择执行路径。模型识别不构成文件修改权限，也不替代来源及计算核对。不能可靠识别时说明依据和具体问题，不猜类型。

科目余额表和序时账不是所有项目的统一必备资料。资产负债表与银行资料足以支持单一银行资产项目时，使用空的科目明细集合进入轻量流程，不生成虚构科目余额表。其他组合缺少明细证据时列示对应非零项目，不笼统要求固定文件名称。当前自动填报适配器不支持的来源布局须明确说明，不能将模型识别成功等同于填报成功。

### 先识别现有资料，再判断是否缺明细

- 不得因为用户没有单独提供名为“二级明细表”“辅助余额表”或“资产台账”的文件，就直接要求补充资料。
- 在生成 `missing_materials.json` 或向用户提出补充要求前，必须先检查本次已提供的全部相关来源。至少依次判断：资产负债表能否确认科目总额；科目余额表能否拆出二级科目或辅助核算对象；序时账能否按科目、主体、摘要和发生日期还原明细；其他附件能否证明资产名称、权属或数量。
- 例如，用户已提供科目余额表、序时账和资产负债表时，应先尝试从科目余额表与序时账还原应收账款、预付账款、其他应收款、应付账款、预收账款和其他应付款等明细；不得跳过识别而笼统要求用户另行提供二级资料。
- 只有在现有来源已经完成识别、交叉核对后，仍无法证明所需字段或无法拆分到模板要求的明细粒度时，才可列为缺失资料。补充要求必须写明科目、已检查的来源、仍缺少的具体字段或维度，以及为什么现有资料不足。

Produce a complete first-pass valuation declaration workbook from:

- `科目余额表`
- `资产负债表`
- optional `序时账`
- optional detailed schedules such as `固定资产台账`, `无形资产清单`, `长期股权投资明细`, `在建工程明细`

The first pass must be complete enough to circulate internally even when some non-current-asset detail files are still missing.

### 常规业务顺序与特殊项目边界

- 本 skill 的常规职责是先依据账务资料和辅助资料形成评估明细表，为后续评估测算提供资产范围、账面数据和基础参数。
- 不把正式评估报告中的评估结论作为常规上游数据源，也不默认从既有评估结论反向分配或倒填单项评估值。
- 用户明确要求处理特殊倒序项目时，只按该项目的明确口径执行并记录为项目级例外；不得把该例外、特定币种、资产组总值分配方式或合并单元格方案固化为通用流程。

## Mandatory Scope-First Routing

The default route is scope-first, not full-template processing. Follow [scope_first_execution.md](references/scope_first_execution.md).

1. Read the formal balance sheet first and complete the accounting-statement reconciliation required for the selected reporting date.
2. Identify non-zero asset and liability lines. Equity lines still populate the balance sheet, but they do not activate appraisal detail pages.
3. Map only those non-zero lines to detail sheets, then add the smallest summary/formula dependency closure needed to validate them.
4. Write `execution_scope.json` before any detail-page write. It must state the selected mode, active balance-sheet lines, active detail sheets, required dependency sheets, and fallback reason if full-template processing is selected.
5. Default to `scoped_standard`. Select `single_asset_lightweight` when only one supported asset family is non-zero and its detail evidence is complete; bank-only engagements with a usable bank statement are the primary case.
6. Use `full_template` only when the user explicitly requests it, the template is being structurally migrated, or required formula dependencies cannot be closed safely. Record the exact reason; complexity alone is not a reason.

In scoped modes, do not initialize, clean, recalculate, or review unrelated detail-sheet families. Unrelated sheets may be hidden after structural checks. Inspect or repair an out-of-scope sheet only when its existing formula error propagates into a required visible summary, and keep that intervention narrowly limited to the root error.

## Project-Local Mapping Rule

This skill uses a project-local mapping workflow.

- Within one project, TB code to account meaning can be treated as stable evidence.
- Across projects, TB code meaning must never be assumed to be reusable.
- The reusable part is the workflow that builds `project_mapping.json`, not a cross-project fixed code table.
- Every run must build or validate a project-local mapping for the non-zero balance-sheet scope first, then use that mapping to drive:
  - detail-page routing
  - balance-sheet sync
  - summary-chain sync
  - classification reconciliation

Do not hardcode a cross-project rule such as `某个编号前缀 always maps to 某个模板页签`.

## Non-Negotiables

- Preserve workbook structure, formulas, links, formatting, and sheet layout.
- The same protection applies to `汇总表`, `流动资产汇总表`, `存货汇总表`, `非流动资产汇总表`, `可供出售金融资产汇总表`, `固定资产汇总表`, `在建工程汇总表`, `无形资产汇总表`, `流动负债汇总表`, and `非流动负债汇总表`, including short names and trailing spaces. Use the shared `scripts/summary_sheet_policy.py` in registries, writers, footer handling, and validation. Missing registry metadata must never permit writes to a summary sheet. Summary sheets must not be registered as detail pages, cleaned as zero-balance detail bodies, or normalized as detail footers.
- Protect every existing formula inside the classification summary worksheet, including sheets named `分类汇总表`, `分类汇总`, and `资产评估结果分类汇总表`. Never replace these formulas with source amounts, cached results, zero differences, or a literal `OK`.
- Capture formulas on the touched summary sheets and the required dependency closure before filling, compare them before each save and again from the saved staging file before publishing, and emit `summary_formula_preservation_report.json`. A removed, replaced, or rebound formula blocks publication. Do not use `balance_sheet_sync` or a post-processing pass to bypass this check. Untouched, out-of-scope summary families do not require formula-by-formula revalidation unless a structural edit can affect them.
- Reconciliation calculations may update formula caches or validation reports only; they must not replace worksheet formulas. Enable automatic recalculation. Verify on a test copy that editing a detail amount changes its linked summary amount and difference, rather than merely checking the initial `J4` value.
- Treat the prebuilt internal links in `分类汇总`, `流动汇总`, `存货汇总`, `非流动资产汇总`, `固定资产汇总`, `无形资产汇总`, `在建工程汇总`, `流动负债汇总`, and `非流动负债汇总 ` as immutable template assets. Do not modify, delete, recreate, overwrite, rebind, or bulk-refresh these links unless the user explicitly authorizes summary-link structural reconstruction for the current workbook.
- When a formal financial statement or monthly financial report is provided, it is the authoritative source for the workbook `资产负债表`; do not derive the balance sheet only from the trial balance.
- Before writing detail pages, build a balance-sheet row mapping and verify every non-zero financial-statement line against the output workbook.
- Before inserting rows, identify each target sheet's detail body, total row, fixed footer, formulas, hyperlinks, and merged ranges. For six-counterparty sheets, insert only above the fixed footer; never modify the footer block.
- Do not depend on desktop Excel/WPS `Save` or `SaveAs` for unattended production runs. The skill must remain fully automatic and must not trigger modal confirmation dialogs.
- Generate and modify a workbook in an ASCII-named staging path first, then publish to the final Chinese filename with filesystem copy or rename after validation passes.
- Do not write concurrently to the same `.xlsx`; after each save, validate the `.xlsx` as a zip before any further read/write step.
- Never expose old-project residue in in-scope or visible sections. Out-of-scope sheets should normally be hidden and left structurally untouched; clear them only when they enter the required dependency closure or the user requests a full-template cleanup.
- Never fabricate fixed-asset, intangible-asset, long-term-equity-investment, or construction-in-progress detail rows.
- Never fabricate any accounting fact, counterparty, asset item, amount, date, certificate number, PO number, or business description. All detail content and all numeric values must come from the user-provided `科目余额表`, `序时账`, `资产负债表`, or later supplementary source files explicitly provided by the user.
- If a class has only total-book-value evidence and no detail schedule yet, create a placeholder state rather than fake detail.
- If `坏账准备`, `信用减值损失`, `资产减值准备`, or similar deduction items exist in source files, write them to the workbook as `0` or the source amount; do not leave the deduction area blank.
- The acceptance gate requires the `资产评估结果分类汇总表` difference status to be non-error. Treat this as `分类汇总!J4 = OK`; the sheet must never be delivered with `出错`.
- Final delivery must also pass `delivery_check_report.json` from `scripts/validate_delivery_gates.py`.
- Preferred acceptance is `分类汇总!J4 = OK`. If this cannot be achieved from the currently provided source files, submission is still allowed only when the run outputs a precise explanation of why reconciliation cannot be completed yet.
- Hide sheets, row blocks, or sections for accounts not involved in the current `科目余额表` and `资产负债表` instead of exposing unrelated template content in the delivered workbook.
- Any account sheet, row block, or section that is involved in the current `科目余额表` or `资产负债表` must remain visible in the delivered workbook; never hide in-scope content.
- After each write, inspect for `#REF!`, stale text, and unexpected old-project identifiers.
- Do not treat `分类汇总!J4 = OK` as the only completion condition. Passing reconciliation is necessary but not sufficient.
- For any field named `结算对象`, `欠款单位名称`, `往来单位`, or similar, only a company name, person name, or explicit legal/entity subject may be auto-filled.
- Never auto-fill a settlement-object field with:
  - account names
  - sub-account labels
  - business-category labels
  - tax labels
  - currency labels
  - `综合本位币`
  - `人民币`
- If the current source files do not prove a real counterparty/entity, the row must become `placeholder_only` or be listed in `missing_materials.json`; never guess a counterparty.
- `应交税费` pages default to tax-label presentation, not counterparty presentation, unless the template for the current project explicitly defines otherwise.
- `银行存款` pages must use bank statements when provided. Account-number fields must contain only the pure numeric account number.
- `应交税费` pages must use tax returns when provided to fill the tax authority or clearly report that the tax authority source is missing.
- Occurrence-date fields must be written as `YYYY/MM/DD`; do not use `YYYY-MM-DD`.
- Final delivery must not contain `报表差额占位`, `其余明细合计`, `详见缺资料清单`, or `税费调整项` as a substitute for real detail rows.
- For `其他应付款`, a project-confirmed, immaterial suspense item may be accepted as an exception detail row when:
  - supplementary detail explicitly classifies it as `其他应付`
  - no real counterparty can be proven from the available source set
  - the row uses an explicit suspense label such as `待查资金入账`
  - the business description is traceable to a concrete source entry
  - the exception is explicitly accepted for the current project
- Any intermediate workbook, temporary output, or reconciliation-only result with semantic field errors must be treated as failed, not delivered.

## Mandatory Semantic Model

Before writing any detail row, normalize each candidate row into at least:

- `source_account_code`
- `source_account_name`
- `source_aux_text`
- `source_amount`
- `sheet_target`
- `counterparty_name`
- `counterparty_type`
- `business_desc`
- `tax_label`
- `fill_mode`
- `fill_reason`
- `evidence_sources`

Required field meaning:

- `counterparty_name`: only company/person/explicit subject
- `business_desc`: business label, summary, or event description
- `tax_label`: tax type only, mainly for tax sheets
- `fill_mode`: one of `detail_fillable`, `placeholder_only`, `skip`

## Source-Driven Workflow

### Cover Identity And Valuation Date

- Fill the confirmed cover layout on `封面` or `封面页`: company name in `F7` (merged `F7:M7`), year in `F9`, month in `H9`, day in `J9`. Preserve the `G9/I9/K9` date labels, formatting, merges, and all linked formulas. Do not change the separate filling date in `F13/H13/J13`.
- Use `scripts/cover_metadata.py` to read the compilation entity and reporting date from the original balance-sheet header. The company name must match the compilation entity exactly after removing the `编制单位：` or `单位名称：` label.
- For multiple periods, select the latest reporting date only among explicitly supplied statements for the same entity. Never discover unrelated files by scanning the directory, use file modification times, or infer the reporting date from ordinary numeric values. Missing identity/date or conflicting entities must stop filling with an explicit error.
- The job config accepts `financial_statements` as a list of original statement paths; otherwise it uses `balance_sheet`. Select the latest original statement before normalization so both financial data and cover metadata use the same period. Pass the selected original via `--financial-statement` to the pipeline when `--balance-sheet` is a normalized workbook; the original header remains the source of cover metadata.
- Validate the cover layout before writing and re-read the saved workbook before publishing. Produce `cover_source_selection.json` and `cover_fill_report.json` with the source workbook, sheet, source cells, target cells, and validation result.

## Technical Route

Use a pure file-level automation route.

1. Read and reconcile the formal balance sheet, then create `execution_scope.json`.
2. Copy the template workbook to an ASCII-named staging file.
3. Read only the source data needed by the selected scope with `openpyxl` or other non-UI readers.
4. Write workbook content through OOXML-safe file edits or tightly scoped workbook-library writes.
5. Recompute or explicitly populate only the required reconciliation dependency chain in Python instead of depending on desktop Excel or WPS recalculation.
6. Validate the staging workbook within the selected scope and dependency closure.
7. Publish the validated staging workbook to the final Chinese filename with filesystem copy or rename only.

Do not treat desktop Excel or WPS as the production write path. At most, use them as an optional read-only inspection fallback when debugging.

### Stage 1: Determine Scope Before Template Work

Build the balance-sheet scope and page-handling plan before scanning or modifying detail-sheet families. Only in-scope pages and their required dependency sheets belong in the plan.

Classify each workbook section into one of three states:

1. `detail_fillable`
   - The source has enough detail to expand to row level.
2. `placeholder_only`
   - The source has only aggregate book value and no supporting detail schedule yet.
3. `zero_balance_cleanup`
   - Use only for a zero-balance page that is in the required dependency closure, contains visible residue, or is included by an explicit full-template cleanup request.
4. `not_in_scope_hide`
   - The account or page is not involved in the current source books and should be hidden in the delivered workbook after structural validation.

Always output `execution_scope.json` and a machine-readable page plan before detail writing. The page plan should contain:

- source account code or report line
- target workbook sheet
- handling state
- required supporting files if not yet available

### Stage 2: Build Complete First-Pass Workbook

Create a complete first-pass workbook even if some schedules are missing.

#### Detail-fillable pages

Typical pages:

- `应收账款`
- `预付账款`
- `其他应收款`
- `应付账款`
- `预收账款`
- `其他应付款`
- `职工薪酬`
- `应交税费`

Rules:

- Expand row-level counterparties from the subject-balance workbook when available.
- Use journals to fill `业务内容`, `发生日期`, and `账龄` when possible.
- Write `坏账准备` and similar deduction rows from source balances.
- A detail-fillable row is not considered valid unless the settlement-object field is semantically valid for the current page type.
- If the only available text is a business label such as `技术服务收入`, `押金`, `待抵扣进项税`, `内部资金拆借`, or a tax label, do not auto-fill it into the settlement-object field.
- When a real counterparty is missing, downgrade the row to `placeholder_only` or list it in `missing_materials.json`.

#### Placeholder-only pages

Typical pages:

- `固定资产汇总`
- `固定资产` subpages
- `在建工程`
- `长期股权投资`
- `无形资产汇总`
- `无形-其他`
- `开发支出`
- `长期待摊费用`

Rules:

- 在确认现有来源不能可靠拆分二级明细后，如资产负债表、科目余额表或其他可靠来源能够证明科目总额，先将该总额写入模板合法的汇总输入格或明确的总额站位行，使相关汇总表能够完成勾稽核验。总额站位只能表达“已核实总额、明细待补”，不得虚构资产名称、数量、权属编号、交易对手或其他事实。
- 总额站位行应使用清晰标签，如 `按科目总额暂列（待补明细）`，并在 `placeholder_pages.json`、`missing_materials.json`、`field_lineage_report.json` 和用户交付说明中记录来源、金额、缺失的明细维度及后续替换范围。
- 如果模板有专用汇总输入格，优先使用该输入格；只有汇总链必须依赖明细行合计且模板没有合法汇总输入格时，才使用总额站位行。
- 除上述合法的总额站位行外，在没有明细证据时保持其他明细行为空。
- Preserve all formulas and links.
- The prebuilt links in `分类汇总`, `流动汇总`, `存货汇总`, `非流动资产汇总`, `固定资产汇总`, `无形资产汇总`, `在建工程汇总`, `流动负债汇总`, and `非流动负债汇总 ` are not fill targets and must remain untouched.
- Mark these pages as `待补资料回填`, and include them in the missing-materials list.
- 缺少二级明细只暂停该科目的明细完整性认定，不得阻断其他已有充分证据科目的填报和校验。工作簿可作为“待补明细版”交付，但不得将对应科目标记为 `detail_fillable` 或宣称完整明细已经完成。

#### Zero-balance cleanup pages

Rules:

- Do not sweep every zero-balance family. Clear historical body content only in the scoped sheet group or where residue affects a required visible dependency.
- Keep sheet titles, page headers, footer formulas, merged-cell layout, return links, and summary formulas intact.
- Clear old project text such as device IDs, PO numbers, equipment names, trademarks, patent numbers, historical asset codes, or unrelated companies.
- If a page is outside current scope entirely, prefer hiding it in the delivered workbook after checks pass.

### Stage 3: Incremental Supplemental Refill

When supplementary detail files arrive, update only the related sheets.

Examples:

- `固定资产台账` -> `固定资产汇总`, `机器设备`, `电子设备`, related fixed-asset pages
- `无形资产清单` -> `无形资产汇总`, `无形-其他`, related intangible pages
- `长期股权投资明细` -> `股权投资`
- `在建工程明细` -> `在建（土建）`, `在建（设备）`, related summary pages

Rules:

- Replace placeholder state with detail state only for the affected sheets.
- Do not rebuild unrelated pages.
- Re-run summary-chain checks after each supplemental refill.

## Required Outputs

Every run must produce:

1. A workbook result.
2. `staging_workbook_path.txt`
3. `published_workbook_path.txt`
4. `source_inventory.json`
5. `project_mapping.json`
6. `balance_sheet_mapping_check.json`
7. `sheet_structure_map.json`
8. `insert_plan.json`
9. `page_plan.json`
10. `completed_pages.json`
11. `placeholder_pages.json`
12. `missing_materials.json`
13. `validation_report.json`
14. `hidden_scope.json`
15. `unreconciled_reasons.json` when `分类汇总!J4` is not `OK`
16. `semantic_validation_report.json`
17. `counterparty_anomaly_report.json`
18. `field_lineage_report.json`
19. `journal_match_report.json`
20. `date_age_fill_report.json`
21. `bank_extract_report.json`
22. `tax_extract_report.json`
23. `reclassification_analysis.json`
24. `delivery_check_report.json`
25. `execution_scope.json`
26. `change_manifest.json`

`missing_materials.json` should list concrete file expectations, for example:

- `固定资产台账`
- `无形资产明细清单`
- `长期股权投资明细`
- `在建工程项目清单`

不得仅按文件名判断资料缺失。每一项缺失资料还必须记录：对应科目、已经检查的来源文件、已经能够确认的总额、尚不能确认的字段或拆分维度，以及建议补充的资料类型。面向用户的交付说明必须逐科目列出这些内容，不能只返回笼统的“请补二级明细”。

## Validation Gates

### 增量校验边界

每次写入前建立 `change_manifest.json`，至少记录本轮实际修改或计划修改的工作表、单元格/区域、公式、合并区域、行列结构、样式、打印设置、工作表显隐状态，以及是否触及超链接或 worksheet relationship。

默认采用增量校验：

- 校验实际修改区域及其直接依赖的汇总链；
- 校验因插行、删行、移动或合并而可能受影响的固定页脚、公式和导航；
- 校验本轮改动对应的来源、金额、语义和显示/打印结果；
- 保留工作簿可打开、ZIP 结构有效等文件级基础检查。

未修改超链接、超链接所在单元格或 worksheet relationship 时，不得逐一重新打开或复核模板中的全部超链接。只需证明本轮写入路径未触及这些对象，并对实际修改工作表执行必要的结构保护检查。

仅在以下情况扩大为全工作簿结构或链接校验：

- 插入、删除或移动行列可能使范围外引用发生位移；
- 重命名、删除、复制或移动工作表；
- 修改跨表公式、定义名称、超链接或 relationship；
- 进行模板迁移、链接重建，或用户明确要求全量检查；
- 无法从 `change_manifest.json` 证明改动与范围外结构相互隔离。

全工作簿桌面 Excel/WPS 重算不是默认验收步骤。优先在 Python 中计算并验证必要依赖链；只有公式缓存必须刷新且文件级方法不足时，才执行最多一次最终全工作簿重算。修复后只复核修复点及受其影响的依赖链，不因一次局部修复重复全量检查。

Before declaring completion, validate:

- The workbook zip structure is valid after the final save.
- The output `资产负债表` ties exactly to the formal financial statement when one is provided.
- No `#REF!` in touched sheets, visible sheets, or the required dependency closure.
- No old-project identifiers remain in `zero_balance_cleanup` sheets.
- Placeholder-only sheets contain no fabricated detail rows.
- Deduction rows such as `坏账准备` or `减值准备` are filled with source amount or `0`, not left blank.
- Summary-chain formulas still link correctly to the intended source sheets.
- `分类汇总` and `汇总表` remain structurally consistent with the template.
- `分类汇总!J4` must be `OK`, not `出错`.
- `分类汇总` difference row count must be zero.
- Occurrence-date fields must use `YYYY/MM/DD`.
- Bank account fields must be pure digits.
- Six-counterparty fixed footers must remain intact.
- No forbidden final placeholders such as `报表差额占位` or `其余明细合计`.
- The `分类汇总` difference column must reconcile to zero or template-allowed blank states after placeholder placement and supplemental refills.
- When placeholder-only pages feed summary sheets, the corresponding `资产负债表` or aggregate placeholder writes must be sufficient to avoid `分类汇总` difference failures.
- Hidden sheets or hidden rows must not break formulas, links, or required navigation.
- The delivered workbook should expose only in-scope account pages plus required structural summary sheets; hidden out-of-scope sheets do not require full evaluation unless they feed the selected dependency closure.
- Any account present in either source book must remain visible in the delivered workbook, even if it is only a placeholder-only page.
- If `分类汇总!J4` is not `OK`, `unreconciled_reasons.json` must explain the exact reason, affected rows, current source evidence boundary, and required missing files or structural blockers.
- When the sources do not support a value, leave it blank, placeholder-only, or explicitly unreconciled; do not guess.
- 对 `placeholder_only` 科目，应核对总额站位金额与来源科目总额一致，并确认其能够沿必要汇总链勾稽；不得因总表已经勾稽而把总额站位误判为二级明细已完成。
- 在报告资料缺失前，验证记录必须证明已经检查本次提供的科目余额表、序时账、资产负债表及相关附件，并说明为什么这些来源仍不足以恢复所需明细。
- Any `detail_fillable` page must also pass semantic validation, not only numeric validation.
- A run fails if a settlement-object field contains a business label, tax label, currency label, or account label instead of a real subject.
- A run fails if `结算对象 == 业务内容`, unless the current project has an explicit documented exemption.
- A run fails if a detail page has non-zero row count but its key semantic fields are empty or semantically invalid.
- A run fails if a reconciliation-only fix makes `J4 = OK` while leaving semantically invalid detail rows in place.

## Implementation Guidance

### Mandatory Post-Generation Review and Release

- Follow [post_generation_review.md](references/post_generation_review.md) for every run. These requirements override any older allowance to publish first and validate later.
- Reopen the saved staging workbook and original source files. Writer bookkeeping and equal grand totals are not sufficient evidence of field correctness or completeness.
- Check source identity, company, period, amount and direction, counterparty coverage, journal-supported descriptions/dates, protected formulas, calculated results, and workbook structure before publication.
- Never create balancing rows, delete a source row because its amount equals a discrepancy, substitute zero for missing calculation results, or promote an uncalculated J4 to OK.
- Repair only uniquely evidenced writable input cells, then repeat validation. Do not repair summary formulas by writing cached numbers into cells.
- Any unresolved blocking difference or unverified populated field prevents publication and `complete`. Leave the previous delivery untouched.
- Always read and relay `user_feedback.md` to the user, including unresolved locations, differences, required materials and publication status. JSON reports alone are not user feedback. Accepted blank journal fields and authorized placeholder-only pages must also be disclosed.

- Use pure file-level workbook automation as the default writer.
- In `single_asset_lightweight`, validate stage-1 balance-sheet inputs directly and perform at most one final workbook recalculation. Do not run a desktop full-workbook recalculation merely to decide which pages are in scope.
- In `scoped_standard`, restrict structure scanning, cleanup, semantic review, and formula-error review to active pages plus their dependency closure.
- 遵循 `change_manifest.json` 的增量校验范围；模板资产“不得修改”不等于每轮必须逐项重验所有未修改公式和超链接。
- A switch to `full_template` must be visible in `execution_scope.json` with a concrete structural reason or an explicit user request.
- Prefer one of these routes:
  - scoped `openpyxl` writes when they do not break workbook structure
  - direct OOXML sheet-XML patching when template preservation is fragile
- Do not rely on desktop Excel or WPS save prompts, recalculation prompts, or UI suppression flags for final delivery.
- For slow cleanup of large sheets, clear only the true body range instead of scanning the entire used range.
- Compute and validate the key summary-chain and `分类汇总` difference-chain in Python so acceptance does not depend on a desktop spreadsheet application.
- Prefer scoped page-family cleanup rules:
  - fixed-asset family
  - intangible-asset family
  - receivable or payable family
- Add project-visible semantic anomaly checks before publish, not only after publish.
- Prefer failing fast with explicit anomaly reports over silently forcing business labels into settlement-object columns.
- Never blanket-wrap formulas with `IFERROR`. A narrow guard is allowed only for the specific out-of-scope hidden leaf formula whose pre-existing division error propagates into a required visible summary; preserve the original formula inside the guard and record the affected cell.

## Strict Execution Reference

When this skill is used, also follow:

- [valuation-detail-workbook-strict-execution-spec.md](/D:/1/1/ai-excel-agent/docs/valuation-detail-workbook-strict-execution-spec.md)

## Manual Override Lessons

When a human-corrected workbook exists, the skill must treat it as evidence of stricter delivery rules than raw numeric reconciliation. In future runs of the same workbook family, the skill should enforce these lessons:

- A final deliverable must preserve footer labels, signature blocks, fill-date fields, and other fixed structural text on touched pages.
- `跨币种中转` and synthetic balancing rows such as `项目内口径补差` must not remain on final receivable or payable detail pages.
- Tax pages must prefer business tax categories. System workflow strings, invoice-processing markers, and raw identifiers are not acceptable final tax labels.
- If a human revision compresses system-style technical content into cleaner business wording, the skill should prefer the cleaner business wording in future outputs.
- If a row cannot support a real occurrence date from the available evidence, the skill must either surface the evidence boundary explicitly in `备注` or fail under the current project rule, rather than pretending the field is complete.

## Repo Scripts To Evolve

This skill should evolve these repo scripts instead of adding ad hoc one-offs:

- [scripts/fill_arap_detail_from_balance.py](/D:/1/1/ai-excel-agent/scripts/fill_arap_detail_from_balance.py:1)
- [scripts/rebuild_arap_detail_workbook_com.py](/D:/1/1/ai-excel-agent/scripts/rebuild_arap_detail_workbook_com.py:1)
- [scripts/build_detail_stage_bs_only.py](/D:/1/1/ai-excel-agent/scripts/build_detail_stage_bs_only.py:1)
- [scripts/build_detail_arap_rows.py](/D:/1/1/ai-excel-agent/scripts/build_detail_arap_rows.py:1)
- [scripts/fill_detail_arap_workbook.py](/D:/1/1/ai-excel-agent/scripts/fill_detail_arap_workbook.py:1)
- [scripts/generate_detail_workbook_staged.py](/D:/1/1/ai-excel-agent/scripts/generate_detail_workbook_staged.py:1)
- [scripts/apply_detail_cleanup_com.py](/D:/1/1/ai-excel-agent/scripts/apply_detail_cleanup_com.py:1)

## References To Read When Needed

- For workbook link and formula preservation, read [asset_based_template_relationships.md](/D:/1/1/ai-excel-agent/.codex/skills/asset-based-excel-links/references/asset_based_template_relationships.md:1).
- For template-family logic and checks, read [asset-based-excel-links SKILL.md](/D:/1/1/ai-excel-agent/.codex/skills/asset-based-excel-links/SKILL.md:1).

## Six Page-Type Date Rules

- `应收账款`: positive receivable balances use the last real debit-side business date; `账龄` is required.
- `预付账款`: positive receivable balances use the last real debit-side business date; `账龄` is required.
- `其他应收款`: positive receivable balances use the last real debit-side business date; `账龄` is required.
- `应付账款`: positive payable balances use the last real credit-side business date; `账龄` is not required if the template has no aging field.
- `预收账款`: positive payable balances use the last real credit-side business date; `账龄` is not required if the template has no aging field.
- `其他应付款`: positive payable balances use the last real credit-side business date; `账龄` is not required if the template has no aging field.

Shared fallback rule:

- Filter reversal/red-ink/correction/carryforward noise first.
- If no real business record can be proven from the provided evidence, do not invent a date.
- If the current project accepts evidence-boundary delivery for a row, leave the date blank and explain the boundary in `备注`.
