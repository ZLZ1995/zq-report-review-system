# S21 execution ledger: scoped file-content access

## Scope

- Give the Agent an actual content-reading tool instead of metadata-only file
  listings.
- Keep reads limited to files registered in the current project.
- Bound content size and expose truncation/unsupported-format diagnostics.

## Changes

- Added `BusinessRunService.read_file_content`.
- Added the `read_project_file` local-readonly Agent tool.
- Supported bounded UTF-8 text/CSV/JSON, DOCX paragraphs/tables, and XLSX/XLSM
  sheet previews; arbitrary filesystem paths are never accepted.
- Updated tool catalog expectations from seven to eight business tools.

## Verification

- New scoped/bounded read test: passed.
- Tool assembly and catalog regression tests: 2 passed.
- Previous full Agent rebuild result before the expectation-only updates:
  381 passed, 9 xfailed; the only failures were the two expected tool-count
  assertions, now corrected. The corrected tests pass.

## Gate

S21 is **passed** for bounded file-content access. Legacy `.xls` and PDF
content extraction still require dedicated adapters and are tracked as a
follow-up; no false claim of full binary-format coverage is made.

## Next action

Wire a composite operation resolver so Skill snapshots, business tools,
browser tools, and file scope are persisted together and pinned for recovery.
