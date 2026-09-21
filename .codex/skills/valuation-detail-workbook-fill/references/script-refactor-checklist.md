# Script Refactor Checklist

## 1. Replace one-off scripts with staged pipeline

Target scripts:

- `scripts/fill_arap_detail_from_balance.py`
- `scripts/rebuild_arap_detail_workbook_com.py`
- `scripts/generate_detail_workbook_staged.py`
- `scripts/apply_detail_cleanup_com.py`

Refactor into:

- `stage_0_prepare_staging_workbook.py`
- `stage_1_scan_sources.py`
- `stage_2_build_placeholder_workbook_filelevel.py`
- `stage_3_apply_supplemental_details_filelevel.py`
- `stage_4_reconcile_classification.py`
- `stage_5_validate_and_publish.py`

## 2. Add explicit page plan generation

`stage_1_scan_sources.py` should output:

- account code
- target sheet
- handling state
- required missing files

## 3. Make placeholder handling first-class

Add helpers for:

- aggregate-only book-value placement
- family-level zero-balance cleanup
- footer deduction placement
- source-evidence tagging for every written region

## 4. Move all final writes to Excel COM
## 4. Remove desktop save-chain dependency

Do not use desktop Excel or WPS `Save` or `SaveAs` as the production write path.

Preferred responsibilities:

- `openpyxl`: source reading and safe scoped writes
- OOXML patch helpers: fragile template-preservation writes
- desktop Excel or WPS: optional read-only debugging only

## 5. Add validation artifacts

Emit:

- residue hit list
- broken-formula list
- placeholder-page confirmation
- missing-materials list
- `分类汇总` reconciliation report
- `J4` acceptance result
- `hidden_scope.json`
- `unreconciled_reasons.json` when applicable
- staging-versus-published path report

## 6. Add residue patterns

Detect:

- PO numbers
- old asset codes
- trademarks
- patent numbers
- prior project company names
- old device names

## 7. Add sheet-family cleanup maps

Examples:

- fixed-asset family: `固定资产汇总`, `房屋建筑物`, `构筑物`, `井巷`, `管道沟槽`, `机器设备`, `车辆`, `电子设备`
- intangible family: `无形资产汇总`, `无形-土地`, `无形-矿业权`, `无形-其他`, helper sheets like `Sheet2`

## 8. Add in-scope versus hidden-scope planning

`stage_1_scan_sources.py` should compute:

- `in_scope_sheets`
- `in_scope_row_blocks`
- `hidden_sheets`
- `hidden_row_blocks`

Hide only after formula validation confirms no broken references.
Never include any sheet or row block in hidden scope if it is present in either source book.

## 9. Add timeout-safe targeted cleanup

Never scan the whole workbook blindly.

Use configured body ranges by sheet family so large sheets can be cleaned deterministically within one run.

## 10. Add reconciliation-aware placeholder writes

When non-current-asset detail schedules are missing:

- placeholder totals must still feed the correct summary sheets
- related `资产负债表` / `分类汇总` linkage must be updated so the difference column does not fail
- do not accept a workbook if placeholder logic leaves `分类汇总!J4` as `出错`
- if `J4` still cannot be made `OK` from current sources, require structured unreconciled-cause output rather than silent acceptance

## 11. Add Python-side reconciliation engine

Implement a deterministic reconciliation module that:

- computes the expected `分类汇总` values from touched source sheets
- checks `企业报表数` versus `账面价值`
- produces `difference_hits`
- writes or validates the `J4` acceptance outcome without depending on desktop spreadsheet recalculation
