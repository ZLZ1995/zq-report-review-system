# Workflow Spec

## Page Handling States

- `detail_fillable`
- `placeholder_only`
- `zero_balance_cleanup`
- `not_in_scope_hide`

## Required JSON Artifacts

- `source_inventory.json`
- `project_mapping.json`
- `balance_sheet_mapping_check.json`
- `sheet_structure_map.json`
- `insert_plan.json`
- `staging_workbook_path.txt`
- `published_workbook_path.txt`
- `page_plan.json`
- `completed_pages.json`
- `placeholder_pages.json`
- `missing_materials.json`
- `validation_report.json`
- `unreconciled_reasons.json` when `J4` is not `OK`
- `semantic_validation_report.json`
- `journal_match_report.json`
- `date_age_fill_report.json`
- `bank_extract_report.json`
- `tax_extract_report.json`
- `reclassification_analysis.json`
- `delivery_check_report.json`

## Technical Route

- Use an ASCII-named staging workbook during generation.
- Avoid desktop Excel or WPS as the production save path.
- Publish the final workbook by filesystem copy or rename after validation.
- Recompute key reconciliation outputs in Python instead of relying on spreadsheet-application recalculation.
- Do not write concurrently to the same `.xlsx`.
- Validate `.xlsx` zip integrity after each save and before any subsequent read/write step.
- If the workbook is locked by Excel/WPS, write a new versioned copy and record the save note.

## Stage Order

1. `scan_sources`: create `source_inventory.json` and classify source evidence.
2. `build_project_mapping`: create project-local account/report/sheet mapping.
3. `fill_balance_sheet`: fill the workbook balance sheet from the formal financial statement when available.
4. `balance_sheet_gate`: produce `balance_sheet_mapping_check.json`; stop if the balance sheet does not tie.
5. `scan_template_structure`: identify detail bodies, total rows, fixed footers, formulas, links, and merged ranges.
6. `fill_bank`: use bank statements for bank name, pure numeric account number, currency, and balance.
7. `fill_arap_from_six_balance`: expand six-counterparty pages from the six-counterparty balance schedule.
8. `fill_journal_fields`: use journals only for business content, occurrence dates, age, and evidence.
9. `fill_tax`: use tax returns for tax authority and tax labels.
10. `reclassification_analysis`: analyze AR/AP/prepayment/advance and report-line reclassifications before writing them.
11. `fill_placeholder_pages`: write aggregate-only placeholders for supported balances lacking detail schedules.
12. `cleanup_zero_scope`: remove template residue from zero-balance/out-of-scope areas.
13. `reconcile_summary_chain`: validate summary/classification chains in Python.
14. `semantic_validate`: validate counterparty, business content, date, account, and tax semantics.
15. `delivery_gate`: run `validate_delivery_gates.py` and produce `delivery_check_report.json`.
16. `publish`: publish only after all gates pass.

## Page Family Rules

### Receivable or Payable Family

- Expand rows from subject balance where counterparty detail exists.
- Fill journals into `业务内容`, `发生日期`, `账龄`.
- Write deduction footer rows.

### Fixed Asset Family

- If no fixed-asset register exists and total balance is zero:
  - clear summary and detail body areas
  - keep headers, formulas, links
- If no fixed-asset register exists and total balance is nonzero:
  - write placeholder book value in summary chain
  - keep body rows empty
  - add `固定资产台账` to missing materials

### Intangible Asset Family

- If no intangible schedule exists and total balance is zero:
  - clear historical body data
- If no intangible schedule exists and total balance is nonzero:
  - placeholder summary only
  - add `无形资产明细清单` to missing materials

### LT Equity or CIP Family

- Placeholder summary only when source has aggregate balance but no schedule.

### Not-in-scope pages

- If a page or row block is not involved in the current `科目余额表` and `资产负债表`, hide it in the delivered workbook after formula validation passes.
- Do not hide required structural sheets such as `封面`, `资产负债表`, `汇总表`, `分类汇总`, or any active bridge sheet still referenced by formulas.
- If a page or row block is involved in either source book, it must remain visible, even when the page is only carrying placeholder totals.

## Source Evidence Rule

- All detail content and numeric values must come from user-provided source files.
- Allowed sources are:
  - `科目余额表`
  - `资产负债表`
  - `序时账`
  - `六大往来科目余额明细`
  - `银行对账单`
  - `纳税申报表`
  - later supplementary schedules explicitly provided by the user
- If the current sources do not support a value, do not invent it.
- If a staging workbook cannot reach `J4 = OK` from current sources, explain the unreconciled reason rather than forcing a guessed value.
- When a formal financial statement or monthly financial report is present, it is authoritative for the workbook `资产负债表`.
- Template sheet presence alone does not create project scope. Scope must come from the financial statement and trial balance.

## Validation Checks

- `.xlsx` zip integrity after save
- balance sheet row-by-row tie to formal financial statement
- `资产总计 = 负债和所有者权益总计`
- old project residue text
- `#REF!`
- deduction footer blanks
- broken summary formulas
- mismatch between placeholder state and actual page content
- `分类汇总!J4 = OK`
- `分类汇总` difference column must not show `出错`
- `分类汇总` difference row count must be zero
- occurrence dates must be `YYYY/MM/DD`
- bank account fields must be pure digits
- six-counterparty fixed footer blocks must remain intact
- no final rows named `报表差额占位`, `报表差额`, `其余明细合计`, `详见缺资料清单`, or `税费调整项`
- placeholder writes must still satisfy `企业报表数` versus `账面价值` reconciliation rules
- hidden scope must match the page plan and must not introduce formula or link failures
- in-scope pages must not appear in `hidden_scope.json`
- If `J4` is not `OK`, `unreconciled_reasons.json` must explain:
  - why it cannot be reconciled from current sources
  - which rows are affected
  - what missing files are required
  - whether the issue is source-gap, placeholder-gap, or formula-chain gap
