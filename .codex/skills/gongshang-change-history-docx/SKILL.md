---
name: gongshang-change-history-docx
description: 从工商变更 Excel 或原始章程、章程修正案、变更登记 PDF 整理公司历史沿革，按锁定模板交付经过内容和字体校验的 Word 文件。PDF 先核对原页并整理为有来源依据的标准变更记录，再进入统一生成流程。
---

# 工商历史变更 DOCX

## 交付与输入路由

- 用户要求“整理历史沿革 / 调用历史沿革 skill”时，默认交付可下载的 `.docx`，文字摘要不能替代文件。只有用户明确只要文字或分析时才不生成 Word。
- 工商 Excel：识别表头后进入下述 Core Workflow。
- 章程、修正案或变更登记 PDF：先读 `references/pdf_sources.md`，逐页核对事实与日期，生成事实表及标准中间 Excel，再进入同一个锁定模板生成器。当前平台输入接口仅接受 `.xlsx`，不能将 PDF 改扩展名传入，也不能据此跳过模板流程。
- 固定产出 `history_fragment.docx`、`history_events.json`、`history_validation.json`；最终回复链接 Word 文件。复用到其他报告时另读模块交接契约。

## 用户确认的文字格式

- 中文字体继承锁定模板；当前绑定模板的正文与表格均为仿宋，西文及数字为 Times New Roman。不要从 Normal 样式猜字体，也不要使用旧脚本中的宋体默认值。
- 表格外正文全部使用小四（12 磅），首行缩进 2 字符；使用字符单位，不以固定厘米值替代。
- 表格内所有文字使用小五（9 磅），首行缩进 0，包括表头、股东名称、金额、比例、合计和追加事项行，不再按列缩小字号。
- 上述两项优先于旧模板、旧脚本或人工参考文档中的冲突格式；仅调整字号及首行缩进，保留其余字体、加粗、对齐、行距、表格网格、合并关系和页眉页脚。
- 完成模板/参考格式复制后统一应用，并重新读取生成文件验证；正文 OOXML 的 `w:firstLineChars` 为 `200`，表格为 `0`，清除冲突的悬挂缩进设置。
- 替换正文或单元格文字时保留对应模板文字运行的完整 `w:rPr`。直接赋值 `paragraph.text` / `cell.text` 会删除运行格式；使用保留格式的替换函数。新增段落及表格行必须由对应模板原型复制。
- 保存后逐个非空文字运行检查 `w:rFonts` 的 `eastAsia/ascii/hAnsi/cs` 与模板一致，并检查 `w:sz` 和 `w:szCs` 均存在且正确。缺失属性视为失败，不能让空集合检查误判通过。`template_fonts_preserved` 失败时不得发布正式 Word。

## 锁定模板约束

- 本平台使用用户确认的固定模板，不允许运行时选择其他模板或以通用版式替代。
- 只在锁定模板副本的指定填充区域写入本次资料。保留模板段落样式、表格网格、合并关系、页眉页脚及固定文本；不得清空整个文档后重新拼版。
- 模板原件只读，生成前后校验 SHA256。绑定缺失、哈希不符或填充区域未确认时停止，不自动查找旧项目文件充当模板。
- 平台模板绑定见 `template.lock.json`。指定填充区域为五组“【变更日期】/【变更事项】段落＋后接表格＋空白间隔”；按实际事件重复该块，股权表沿用第一张7列表，普通事项沿用第四张3列表。区域外固定内容与其他DOCX包部件不得改动。
- 平台执行入口为 `asset_based_agent.technical_platform.history_generation`，不使用下文旧 CLI 的全正文清空重建路径。模板绑定、内容回读和来源校验通过后才发布；程序发布另需样例与分页验收。
- 相邻期间补金额必须有相同股东集合及明确金额证据；不得把退出股东的金额按顺序分配给新增股东。

Use the same locked-template generator after either source route has produced verified change records.

## Required Inputs

- Source Excel: contains a sheet like `变更信息` with columns `变更日期`, `变更事项`, `变更前`, `变更后`.
- Word template: use `template.lock.json` only.
- Optional human-corrected DOCX: use as a comparison reference; conflicting formatting does not override the locked template or the confirmed text rules.

If paths contain Chinese characters, copy inputs to an ASCII working folder before automation when tools are unstable. Avoid PowerShell for Chinese text-heavy parsing; use bundled Python where possible.

## Core Workflow

1. Inspect Excel and identify the real header row. Ignore vendor disclaimer rows.
2. Group records by `变更日期`, sorted oldest to newest.
3. Build a fact sheet before drafting:
   - Current snapshot facts from the enterprise overview, especially `法定代表人`, `企业类型`, `注册资本`, `成立日期`.
   - Event facts from the change-history table.
   - Explicitly separate `confirmed facts` from `inferred facts` when the source is screenshots or partial exports rather than the original Excel.
4. Filter events and items using `references/rules.md`.
5. Generate one event paragraph per retained date.
6. Build tables:
   - Use a 7-column股权 table when the date has actual股东/出资金额/持股比例变化.
   - Use a 3-column事项 table for substantive non-equity changes when there is no股权 table.
   - When a股权 date also has `注册资本变更` or `企业类型变更`, append those rows to the 7-column table bottom.
7. Validate both structure and business consistency:
   - Event count, table count, table shapes, row text.
   - `主要人员变更` must not be silently upgraded to `法定代表人变更` unless the source explicitly says `法定代表人变更` / `法人代表变更`.
   - If the latest enterprise snapshot says `法定代表人 = X`, the retained change chain and ending summary must be able to explain why the latest legal representative is `X`.
   - If `企业类型` changes to `有限责任公司（法人独资）`, the post-change equity table must collapse to one shareholder on the `变更后` side.
8. Reopen the DOCX and validate template fonts, sizes and character indents. Render or export through Word/PDF snapshots when available and inspect every page for overflow, broken rows, blank pages and inconsistent text appearance.
9. Iterate until generated content and snapshot layout match the human-corrected reference if one is supplied.

## Module Output Contract

When this skill is used as a submodule for a formal valuation report, read `references/module_contract.md` and produce the standard three-file interface:

- `history_events.json`
- `history_fragment.docx`
- `history_validation.json`

The fragment is the only artifact that a valuation-report writer should insert into the final report. The validation JSON must be `ok: true` before any consumer inserts the fragment.

Do not allow a consuming report skill to recreate the equity table itself. This skill owns all工商历史沿革 content generation, including equity-table structure, total rows, and same-day item organization.

## Bundled Scripts

- `scripts/build_gongshang_docx.py`: reusable parsing and template-preserving text/table helpers, imported by the platform generator. Its legacy CLI is not the locked-template delivery entry.
- `scripts/compare_docx_structure.py`: extracts event paragraphs and table text from generated and human-corrected DOCX files.
- `scripts/export_compare_snapshots.ps1`: uses local Microsoft Word COM automation to export two DOCX files to PDF for visual comparison.
- `scripts/render_compare_pdfs.py`: renders PDFs to page thumbnails/contact sheets using `pypdfium2` and PIL.

Use `asset_based_agent.technical_platform.generation_worker` with a job JSON containing `skill_id` and `inputs.source_excel` / `inputs.template`; resolve the template with `generation.locked_template` first. Each job uses a fresh output directory. Do not change skill path constants for each company or call the legacy full-document rebuild CLI.

## Validation Standard

When a human-corrected reference is available, do not stop at “file generated”. Confirm:

- Same retained event paragraphs.
- Same table count and table row/column shapes.
- Same table text row by row.
- Same page count after Word export.
- Contact-sheet snapshot shows the same content distribution across pages.

Even when no human-corrected reference is available, do not stop at “structurally valid”. Confirm at minimum:

- The final legal representative stated in the fragment is supported by explicit `法定代表人变更` records or by the current enterprise snapshot.
- `主要人员变更` rows are not rewritten as legal-representative changes unless the source explicitly says so.
- `法人独资` / `自然人独资` / `自然人投资或控股` conclusions are consistent with the shareholder count shown in the equity table.

Additional minimum equity validation:

- Equity detail rows must sum to the total row on both amount and ratio columns.
- Equity shareholder rows with a name must include both amount and ratio, and names must be unique on each side.
- If a fact sheet is provided, equity holder/amount maps in the table must match `fact_sheet.confirmed_facts` for the same date and side.

If LibreOffice is unavailable, prefer Microsoft Word COM export on Windows. If neither renderer is available, disclose that visual QA was skipped and provide only structural validation.

## Reference Rules

Read `references/rules.md` before implementing or revising generation logic.

Read `references/module_contract.md` before generating a reusable history fragment for insertion into another formal document.
