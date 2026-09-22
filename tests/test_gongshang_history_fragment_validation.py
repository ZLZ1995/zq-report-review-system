from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / ".codex"
    / "skills"
    / "gongshang-change-history-docx"
    / "scripts"
    / "build_history_fragment.py"
)


def load_fragment_module():
    spec = importlib.util.spec_from_file_location("build_history_fragment", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fragment_file(tmp_path: Path) -> Path:
    path = tmp_path / "history_fragment.docx"
    path.write_bytes(b"placeholder")
    return path


def shujike_event(after_rows: list[dict[str, str]]) -> dict:
    total = "\u5408\u8ba1"
    project = "\u80a1\u4e1c\u51fa\u8d44\u91d1\u989d\u53ca\u6301\u80a1\u6bd4\u4f8b"
    return {
        "date": "2024-10-08",
        "equity_rows": [
            {
                "project": project,
                "before_name": "\u6768\u52c7",
                "before_amount": "150.00",
                "before_ratio": "15.0000%",
                **after_rows[0],
            },
            {
                "project": project,
                "before_name": "\u6c5f\u5349",
                "before_amount": "600.00",
                "before_ratio": "60.0000%",
                **after_rows[1],
            },
            {
                "project": project,
                "before_name": "\u5434\u94a2",
                "before_amount": "250.00",
                "before_ratio": "25.0000%",
                **after_rows[2],
            },
            *[
                {
                    "project": project,
                    "before_name": "",
                    "before_amount": "",
                    "before_ratio": "",
                    **row,
                }
                for row in after_rows[3:]
            ],
            {
                "project": project,
                "before_name": total,
                "before_amount": "1000.00",
                "before_ratio": "100.0000%",
                "after_name": total,
                "after_amount": "1000.00",
                "after_ratio": "100.0000%",
            },
        ],
        "normal_rows": [],
    }


def shujike_fact_sheet() -> dict:
    return {
        "fact_sheet": {
            "confirmed_facts": [
                {
                    "field": "2024-10-08_equity_change_after",
                    "value": (
                        "\u738b\u5ba3600.00\u4e07\u5143\u3001"
                        "\u5434\u94a2250.00\u4e07\u5143\u3001"
                        "\u674e\u514b70.00\u4e07\u5143\u3001"
                        "\u6234\u4e16\u51e140.00\u4e07\u5143\u3001"
                        "\u82cf\u5409\u751f30.00\u4e07\u5143\u3001"
                        "\u8521\u6613\u743410.00\u4e07\u5143"
                    ),
                }
            ]
        }
    }


def validation_by_id(validation: dict, check_id: str) -> list[dict]:
    return [check for check in validation["checks"] if check["id"] == check_id]


def test_equity_validation_fails_when_detail_sum_does_not_match_total(tmp_path):
    module = load_fragment_module()
    missing_wugang_after_rows = [
        {"after_name": "\u674e\u514b", "after_amount": "70.00", "after_ratio": "7.0000%"},
        {"after_name": "\u738b\u5ba3", "after_amount": "600.00", "after_ratio": "60.0000%"},
        {"after_name": "\u6234\u4e16\u51e1", "after_amount": "40.00", "after_ratio": "4.0000%"},
        {"after_name": "\u82cf\u5409\u751f", "after_amount": "30.00", "after_ratio": "3.0000%"},
        {"after_name": "\u8521\u6613\u7434", "after_amount": "10.00", "after_ratio": "1.0000%"},
    ]

    validation = module.validate_events(
        [shujike_event(missing_wugang_after_rows)],
        fragment_file(tmp_path),
        shujike_fact_sheet(),
    )

    assert validation["ok"] is False
    assert validation_by_id(validation, "equity_after_amount_sum_matches_total")[-1]["ok"] is False
    assert validation_by_id(validation, "equity_after_ratio_sum_matches_total")[-1]["ok"] is False
    assert validation_by_id(validation, "equity_after_matches_confirmed_fact_sheet")[-1]["ok"] is False


def test_equity_validation_passes_when_detail_sum_matches_total_and_fact_sheet(tmp_path):
    module = load_fragment_module()
    corrected_after_rows = [
        {"after_name": "\u674e\u514b", "after_amount": "70.00", "after_ratio": "7.0000%"},
        {"after_name": "\u738b\u5ba3", "after_amount": "600.00", "after_ratio": "60.0000%"},
        {"after_name": "\u6234\u4e16\u51e1", "after_amount": "40.00", "after_ratio": "4.0000%"},
        {"after_name": "\u82cf\u5409\u751f", "after_amount": "30.00", "after_ratio": "3.0000%"},
        {"after_name": "\u8521\u6613\u7434", "after_amount": "10.00", "after_ratio": "1.0000%"},
        {"after_name": "\u5434\u94a2", "after_amount": "250.00", "after_ratio": "25.0000%"},
    ]

    validation = module.validate_events(
        [shujike_event(corrected_after_rows)],
        fragment_file(tmp_path),
        shujike_fact_sheet(),
    )

    assert validation["ok"] is True
    assert validation_by_id(validation, "equity_after_amount_sum_matches_total")[-1]["ok"] is True
    assert validation_by_id(validation, "equity_after_ratio_sum_matches_total")[-1]["ok"] is True
    assert validation_by_id(validation, "equity_after_matches_confirmed_fact_sheet")[-1]["ok"] is True
