---
name: gongshang-change-history-docx
description: Generate Chinese工商历史变更 Word documents from 工商/风鸟变更信息 Excel exports and a Word template. Use when Codex needs to split工商变更 records by发生日, filter low-value工商事项, build股东出资金额及持股比例 tables, inherit missing股权金额/比例 from adjacent periods, compare against a human-corrected DOCX, or produce snapshot-verified DOCX outputs for工商历史变更说明.
---

# 工商历史变更 DOCX

## 用户确认的文字格式

- 表格外正文全部使用小四（12 磅），首行缩进 2 字符；使用字符单位，不以固定厘米值替代。
- 表格内所有文字使用小五（9 磅），首行缩进 0，包括表头、股东名称、金额、比例、合计和追加事项行，不再按列缩小字号。
- 上述两项优先于旧模板、旧脚本或人工参考文档中的冲突格式；仅调整字号及首行缩进，保留其余字体、加粗、对齐、行距、表格网格、合并关系和页眉页脚。
- 完成模板/参考格式复制后统一应用，并重新读取生成文件验证；正文 OOXML 的 `w:firstLineChars` 为 `200`，表格为 `0`，清除冲突的悬挂缩进设置。

## 锁定模板约束（优先于下文旧版可选模板说明）

- 本平台使用用户确认的固定模板，不允许运行时选择其他模板或以通用版式替代。
- 只在锁定模板副本的指定填充区域写入本次资料。保留模板段落样式、表格网格、合并关系、页眉页脚及固定文本；不得清空整个文档后重新拼版。
- 模板原件只读，生成前后校验 SHA256。绑定缺失、哈希不符或填充区域未确认时停止，不自动查找旧项目文件充当模板。
- 当前仓库尚未确认正式模板文件及填充区域；客户端生成入口保持阻断，不能据此宣称已完成集成。
- 相邻期间补金额必须有相同股东集合及明确金额证据；不得把退出股东的金额按顺序分配给新增股东。

Use this skill for Chinese工商历史变更说明 workflows where the source is an Excel export of工商变更 records and the deliverable is a Word `.docx` following a provided historical-change template.

## Required Inputs

- Source Excel: contains a sheet like `变更信息` with columns `变更日期`, `变更事项`, `变更前`, `变更后`.
- Word template: contains the target paragraph style and table styles.
- Optional human-corrected DOCX: use it as a format/content reference when available.

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
8. Render or export DOCX through Word/PDF snapshots when available and inspect page thumbnails.
9. Iterate until generated content and snapshot layout match the human-corrected reference if one is supplied.

## Module Output Contract

When this skill is used as a submodule for a formal valuation report, read `references/module_contract.md` and produce the standard three-file interface:

- `history_events.json`
- `history_fragment.docx`
- `history_validation.json`

The fragment is the only artifact that a valuation-report writer should insert into the final report. The validation JSON must be `ok: true` before any consumer inserts the fragment.

Do not allow a consuming report skill to recreate the equity table itself. This skill owns all工商历史沿革 content generation, including equity-table structure, total rows, and same-day item organization.

## Bundled Scripts

- `scripts/build_gongshang_docx.py`: reference implementation from the validated workflow. Adapt the path constants near the top before running.
- `scripts/compare_docx_structure.py`: extracts event paragraphs and table text from generated and human-corrected DOCX files.
- `scripts/export_compare_snapshots.ps1`: uses local Microsoft Word COM automation to export two DOCX files to PDF for visual comparison.
- `scripts/render_compare_pdfs.py`: renders PDFs to page thumbnails/contact sheets using `pypdfium2` and PIL.

Treat the scripts as reusable starting points, not universal APIs. Patch path constants and edge-case rules for the current engagement, then run them.

Before running `build_gongshang_docx.py`, update these constants near the top:

- `XLSX`: source工商变更 Excel.
- `TEMPLATE`: Word template.
- `HUMAN_FORMAT_REFERENCE`: optional human-corrected DOCX for format reference; set to a non-existing path or remove the formatting step if unavailable.
- `OUTPUT`: final generated DOCX path.

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
