# Scope-First Execution

## Purpose

Minimize work without weakening the appraisal workbook's evidence, formula, and reconciliation gates. The balance sheet determines the business scope; the template does not determine it.

## Decision Order

1. Select the authoritative financial statement and reporting date.
2. Reconcile the balance sheet. If the statement is not balanced, stop before detail work unless the user has explicitly confirmed an evidenced adjustment.
3. List non-zero asset and liability report lines. Exclude totals and equity lines from detail-page activation, while still writing equity to the balance sheet.
4. Map each active line to its detail sheet or supported page family.
5. Add only the summary sheets and formula sources needed to connect those detail sheets to the classification summary.
6. Select the execution mode and save `execution_scope.json` before writing details.

## Modes

### `single_asset_lightweight`

Use when exactly one supported asset family is non-zero, no liability detail line is non-zero, and complete evidence exists for that family. For bank-only cases, require a usable bank statement and use only:

- cover
- balance sheet
- bank deposit detail
- current-assets summary
- overall/classification summaries required by the template formula chain

Validate direct balance-sheet input cells after stage 1. Perform no template-wide cleanup and at most one final recalculation.

### `scoped_standard`

This is the general default. Process every non-zero mapped account page, plus the smallest dependency closure required for reconciliation. Zero-balance and unrelated page families are not cleanup targets by default.

### `full_template`

Use only when:

- the user explicitly asks for a full-template rebuild or cleanup;
- the template is being migrated or structurally repaired; or
- a required formula dependency cannot be isolated safely.

Record the exact fallback reason in `execution_scope.json`. Do not choose this mode merely because the template contains many worksheets.

## Required Scope Record

`execution_scope.json` must include:

- `requested_mode`
- `selected_mode`
- `active_balance_sheet_lines`
- `active_detail_sheets`
- `required_dependency_sheets`
- `stage1_excel_recalc_required`
- `reason`

## Validation Boundary

Always validate:

- authoritative balance-sheet equality and mapped input amounts;
- every touched or visible sheet;
- every formula and link in the required dependency closure;
- classification-summary reconciliation and delivery gates.

Do not scan or rewrite hidden, out-of-scope detail families merely to make the whole template appear clean. If an out-of-scope formula error propagates into a required visible summary, repair only the root formula, preserve its logic, and record the intervention.
