from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from openpyxl.utils.cell import coordinate_to_tuple
from summary_sheet_policy import is_linked_summary_sheet


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def coord_in_zone(cell_ref: str, zone: dict[str, int]) -> bool:
    row, col = coordinate_to_tuple(cell_ref)
    return zone["start_row"] <= row <= zone["end_row"] and zone["start_col"] <= col <= zone["end_col"]


def build_sheet_entry(sheet_name: str, layout_meta: dict[str, Any], role: str) -> dict[str, Any]:
    if is_linked_summary_sheet(sheet_name):
        role = 'summary'
    formula_cells = set(layout_meta.get("formula_cells", []))
    summary_zone = layout_meta.get("summary_zone") or {}
    protected_ranges = layout_meta.get("protected_text_ranges", [])
    writable_candidates = set(layout_meta.get("writable_input_candidates", []))

    summary_formula_output_cells = sorted(
        cell for cell in formula_cells if summary_zone and coord_in_zone(cell, summary_zone)
    )

    protected_non_formula_cells: set[str] = set()
    for cell in writable_candidates:
        for protected in protected_ranges:
            zone = {
                "start_row": protected["start_row"],
                "end_row": protected["end_row"],
                "start_col": 1,
                "end_col": layout_meta.get("max_col", 16384),
            }
            if coord_in_zone(cell, zone):
                protected_non_formula_cells.add(cell)
                break

    summary_non_formula_cells = sorted(
        cell
        for cell in writable_candidates
        if summary_zone and coord_in_zone(cell, summary_zone) and cell not in formula_cells
    )

    DETAIL_SUMMARY_INPUT_ALLOWLIST = {
        "银行存款": ["A23", "B23", "C23", "D23", "E23", "F23", "H23"],
        "应收账款": ["A24", "B24", "C24", "D24", "E24", "O24"],
        "预付账款": ["A27", "B27", "C27", "D27", "E27", "G27"],
        "其他应收款": ["A42", "B42", "C42", "D42", "E42", "O42"],
        "应付账款": ["A28", "B28", "C28", "D28", "F28"],
        "预收账款": ["A27", "B27", "C27", "D27", "F27"],
        "其他应付款": ["A51", "B51", "C51", "D51", "F51"],
        "应交税费": ["A27", "B27", "C27", "D27", "F27"],
    }

    legal_input_cells: list[str] = []
    if role == "detail":
        allowlist = DETAIL_SUMMARY_INPUT_ALLOWLIST.get(sheet_name, [])
        legal_input_cells = [cell for cell in allowlist if cell in writable_candidates and cell not in formula_cells]

    status = "confirmed_no_inputs" if not legal_input_cells else "partial_inputs_confirmed"
    return {
        "chain_role": role,
        "legal_input_cells": legal_input_cells,
        "formula_output_cells": sorted(formula_cells),
        "summary_formula_output_cells": summary_formula_output_cells,
        "forbidden_non_formula_cells": sorted(set(summary_non_formula_cells) | protected_non_formula_cells),
        "bottom_region_review_status": status,
        "summary_zone": summary_zone,
        "protected_text_ranges": protected_ranges,
        "notes": [
            "This registry is conservative by default.",
            "No summary-chain cell is considered writable until separately confirmed.",
            "Formula cells are always readonly.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout-map", required=True)
    parser.add_argument("--input-cell-registry", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    layout_map = load_json(Path(args.layout_map))
    input_registry = load_json(Path(args.input_cell_registry))

    selected = input_registry.get("selected_sheets", {})
    entries = {}
    for sheet_name, layout_meta in layout_map.get("sheets", {}).items():
        role = (selected.get(sheet_name) or {}).get("chain_role", "untracked")
        entries[sheet_name] = build_sheet_entry(sheet_name, layout_meta, role)

    payload = {
        "template": layout_map.get("template", ""),
        "sheet_count": len(entries),
        "sheets": entries,
        "policy": {
            "default_summary_inputs": "forbidden_until_confirmed",
            "formula_cells": "readonly",
            "protected_text_ranges": "readonly",
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out.as_posix())


if __name__ == "__main__":
    main()
