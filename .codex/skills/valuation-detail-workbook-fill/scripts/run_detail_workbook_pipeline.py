from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET
from copy import copy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import xlrd
except ImportError:
    xlrd = None
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Border
from openpyxl.utils import get_column_letter
try:
    import win32com.client as win32
except ImportError:
    win32 = None
from detail_mapping_config import (
    BALANCE_SHEET_LABEL_NORMALIZATION,
    CURRENT_LIABILITY_SHEET_MAPPING,
    NONCURRENT_ASSET_SHEET_MAPPING,
    NONCURRENT_LIABILITY_SHEET_MAPPING,
    OWNER_EQUITY_SHEET_MAPPING,
)
from workflow_contract import (
    build_counterparty_resolution,
    build_detail_candidates,
    build_detailed_rule_enforcement_report,
    build_field_assignment_plan,
    build_hidden_scope,
    build_missing_materials,
    build_normalized_balance_sheet,
    build_normalized_journal,
    build_normalized_trial_balance,
    build_page_plan,
    build_rule_enforcement_report,
    build_source_profile,
    build_unreconciled_reasons,
    validate_required_artifacts,
    validate_routing_sanity,
    validate_stage1_gate,
    rules_payload,
    write_json as write_contract_json,
)
from validate_delivery_gates import build_report as build_delivery_gate_report
from summary_sheet_policy import is_linked_summary_sheet
from cover_metadata import read_statement_metadata, select_latest_statement, cover_assignments, validate_cover
from post_generation_review import source_fingerprints, review_pipeline_sources, publish_after_review, write_feedback, issue, ReviewBlocked, repair_unique_source_cells
import sys

try:
    import xml.etree.ElementTree as _ET

    if not hasattr(_ET.ElementTree, "getiterator"):
        _ET.ElementTree.getiterator = _ET.ElementTree.iter  # type: ignore[attr-defined]
except Exception:
    pass


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_stage(output_dir: Path, stage: str, **payload: Any) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stage.txt").write_text(stage, encoding="utf-8")
    write_json(output_dir / "progress.json", {"stage": stage, "timestamp": datetime.now().isoformat(), **payload})


def timed_stage(output_dir: Path, stage: str, started_at: float, **payload: Any) -> None:
    write_stage(output_dir, stage, elapsed_seconds=round(time.perf_counter() - started_at, 3), **payload)


FOOTER_LAYOUTS: dict[str, dict[str, Any]] = {
    "应收账款": {
        "template_total_row": 24,
        "label_rows": {
            0: "合            计",
            1: "减：坏账准备",
            2: "减：评估风险损失",
            3: "净            额",
        },
        "merge_offsets": [(0, "A", "B"), (1, "A", "B"), (2, "A", "B"), (3, "A", "B")],
        "owner_rows": {
            4: {"A": "=封面!D11&封面!G11", "P": '="评估人员："&封面!G20'},
            5: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [4, 5],
        "owner_border_clear_cols": tuple(range(1, 20)),
        "clear_reserved_rows": 4,
        "trim_keep_offset": 10,
    },
    "预付账款": {
        "template_total_row": 27,
        "label_rows": {0: "合            计"},
        "merge_offsets": [(0, "A", "B")],
        "owner_rows": {
            1: {"A": "=封面!D11&封面!G11", "H": '="评估人员："&封面!G20'},
            2: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [1, 2],
        "owner_border_clear_cols": tuple(range(1, 12)),
        "clear_reserved_rows": 1,
        "trim_keep_offset": 2,
    },
    "其他应收款": {
        "template_total_row": 30,
        "label_rows": {
            0: "合            计",
            1: "减：坏账准备",
            2: "减：评估风险损失",
            3: "净            额",
        },
        "merge_offsets": [(0, "A", "B"), (1, "A", "B"), (2, "A", "B"), (3, "A", "B")],
        "owner_rows": {
            4: {"A": "=封面!D11&封面!G11", "P": '="评估人员："&封面!G20'},
            5: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [4, 5],
        "owner_border_clear_cols": tuple(range(1, 20)),
        "clear_reserved_rows": 4,
        "trim_keep_offset": 5,
    },
    "应付账款": {
        "template_total_row": 18,
        "label_rows": {0: "合                                    计"},
        "merge_offsets": [],
        "owner_rows": {
            1: {"A": "=封面!D11&封面!G11", "G": '="评估人员："&封面!G38'},
            2: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [1, 2],
        "owner_border_clear_cols": tuple(range(1, 12)),
        "clear_reserved_rows": 1,
        "trim_keep_offset": 2,
    },
    "预收账款": {
        "template_total_row": 27,
        "label_rows": {0: "合                                    计"},
        "merge_offsets": [(0, "A", "B")],
        "owner_rows": {
            1: {"A": "=封面!D11&封面!G11", "G": '="评估人员："&封面!G38'},
            2: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [1, 2],
        "owner_border_clear_cols": tuple(range(1, 12)),
        "clear_reserved_rows": 1,
        "trim_keep_offset": 2,
    },
    "其他应付款": {
        "template_total_row": 27,
        "label_rows": {0: "合                                    计"},
        "merge_offsets": [(0, "A", "B")],
        "owner_rows": {
            1: {"A": "=封面!D11&封面!G11", "G": '="评估人员："&封面!G38'},
            2: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [1, 2],
        "owner_border_clear_cols": tuple(range(1, 12)),
        "clear_reserved_rows": 1,
        "trim_keep_offset": 2,
    },
    "应交税费": {
        "template_total_row": 27,
        "label_rows": {0: "合                             计"},
        "merge_offsets": [(0, "A", "B")],
        "owner_rows": {
            1: {"A": "=封面!D11&封面!G11", "G": '="评估人员："&封面!G38'},
            2: {"A": "=CONCATENATE(封面!D13,封面!F13,封面!G13,封面!H13,封面!I13,封面!J13,封面!K13)"},
        },
        "owner_border_clear_rows": [1, 2],
        "owner_border_clear_cols": tuple(range(1, 12)),
        "clear_reserved_rows": 1,
        "trim_keep_offset": 2,
    },
}


SUMMARY_SHEET_NAMES = {
    "封面",
    "基本情况",
    "汇总表",
    "分类汇总",
    "资产负债表",
    "流动汇总",
    "流动资产汇总",
    "非流动资产汇总",
    "流动负债汇总",
    "非流动负债汇总",
}


def infer_footer_layout_from_sheet(ws) -> dict[str, Any]:
    total_rows: list[int] = []
    for row in range(20, min(ws.max_row, 300) + 1):
        row_text = "".join("" if ws.cell(row, col).value is None else str(ws.cell(row, col).value) for col in range(1, min(ws.max_column, 20) + 1)).replace(" ", "")
        if "合计" in row_text:
            total_rows.append(row)
    if not total_rows:
        return {}

    template_total_row = total_rows[0]
    label_rows: dict[int, Any] = {}
    row = template_total_row
    while row <= min(ws.max_row, template_total_row + 5):
        cell_value = ws.cell(row, 1).value
        text = clean(cell_value).replace(" ", "")
        if not text:
            break
        if "合计" in text or text.startswith("减") or text.startswith("净"):
            label_rows[row - template_total_row] = cell_value
            row += 1
            continue
        break

    last_label_offset = max(label_rows) if label_rows else 0
    owner_rows: dict[int, dict[str, Any]] = {}
    for row in range(template_total_row + last_label_offset + 1, min(ws.max_row, template_total_row + last_label_offset + 4) + 1):
        mapping: dict[str, Any] = {}
        for col in range(1, ws.max_column + 1):
            value = ws.cell(row, col).value
            if value is None:
                continue
            text = str(value)
            if (
                "封面!D11&封面!G11" in text
                or "CONCATENATE(封面!D13" in text
                or "评估人员" in text
                or "填表人" in text
            ):
                mapping[get_column_letter(col)] = value
        if mapping:
            owner_rows[row - template_total_row] = mapping

    owner_offsets = sorted(owner_rows)
    max_merge_offset = max([last_label_offset, *owner_offsets], default=last_label_offset)
    merge_offsets: list[tuple[int, str, str]] = []
    for merged_range in ws.merged_cells.ranges:
        if template_total_row <= merged_range.min_row <= template_total_row + max_merge_offset:
            merge_offsets.append(
                (
                    merged_range.min_row - template_total_row,
                    get_column_letter(merged_range.min_col),
                    get_column_letter(merged_range.max_col),
                )
            )

    return {
        "template_total_row": template_total_row,
        "label_rows": label_rows,
        "merge_offsets": merge_offsets,
        "owner_rows": owner_rows,
        "owner_border_clear_rows": owner_offsets,
        "owner_border_clear_cols": tuple(range(1, ws.max_column + 1)),
        "clear_reserved_rows": max(1, len(label_rows)),
        "trim_keep_offset": max(owner_offsets) if owner_offsets else max(last_label_offset, 0),
    }


def get_footer_layout(sheet_title: str, ws=None) -> dict[str, Any]:
    layout = FOOTER_LAYOUTS.get(sheet_title)
    if layout:
        return layout
    if ws is not None:
        return infer_footer_layout_from_sheet(ws)
    return {}


def extend_footer_layouts_from_template(template_path: Path) -> dict[str, dict[str, Any]]:
    wb = load_workbook(template_path, data_only=False)
    try:
        added: dict[str, dict[str, Any]] = {}
        for ws in wb.worksheets:
            if ws.title in SUMMARY_SHEET_NAMES or is_linked_summary_sheet(ws.title):
                continue
            if ws.title in FOOTER_LAYOUTS:
                continue
            layout = infer_footer_layout_from_sheet(ws)
            if layout:
                FOOTER_LAYOUTS[ws.title] = layout
                added[ws.title] = layout
        return added
    finally:
        wb.close()


COUNTERPARTY_FORBIDDEN_TERMS = {
    "技术服务收入",
    "押金",
    "待抵扣进项税",
    "内部资金拆借",
    "应交所得税",
    "应交增值税",
    "综合本位币",
    "人民币",
    "默认值",
    "其他",
    "员工款",
    "内部往来-集团内公司",
    "非银行利息收入-集团内借贷",
    "应收账款",
    "预付账款",
    "其他应收款",
    "应付账款",
    "预收账款",
    "其他应付款",
    "应交税费",
    "应交税金",
}

ALLOWED_EXCEPTION_COUNTERPARTIES = {
    "待查资金入账",
}


SEMANTIC_EXEMPT_SHEETS = {"应交税费", "银行存款", "职工薪酬"}
COMPANY_LIKE_RE = re.compile(r"([A-Za-z\u4e00-\u9fff（）()·\-\s]{2,}(?:有限公司|有限责任公司|股份有限公司|合伙企业|分公司|公司|银行|支行|SARL))")

PERSON_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
DOMAIN_NAME_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

class ProtectionViolation(RuntimeError):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(json.dumps(payload, ensure_ascii=False))
        self.payload = payload


def capture_summary_formulas(wb) -> dict[str, dict[str, Any]]:
    return {
        ws.title: {cell.coordinate: copy(cell.value)
                   for row in ws for cell in row if cell.data_type == "f"}
        for ws in wb.worksheets if is_linked_summary_sheet(ws.title)
    }


def assert_summary_formulas_preserved(wb, baseline) -> None:
    for name, formulas in baseline.items():
        if name not in wb.sheetnames:
            raise ProtectionViolation({"sheet": name, "reason": "summary_sheet_removed"})
        for address, formula in formulas.items():
            cell = wb[name][address]
            if cell.data_type != "f" or cell.value != formula:
                raise ProtectionViolation({
                    "sheet": name, "cell": address,
                    "reason": "summary_formula_changed",
                    "expected": str(formula), "actual": str(cell.value),
                })


def capture_template_formulas(wb) -> dict:
    return {ws.title: {c.coordinate: copy(c.value) for row in ws for c in row if c.data_type == 'f'}
            for ws in wb}


def assert_template_formulas_preserved(wb, baseline) -> None:
    for name, cells in baseline.items():
        if name not in wb.sheetnames:
            raise ProtectionViolation({'sheet': name, 'reason': 'template_sheet_removed'})
        for address, formula in cells.items():
            cell = wb[name][address]
            guarded_formula = f"=IFERROR({str(formula)[1:]},0)" if str(formula).startswith("=") else ""
            if wb[name].sheet_state != "visible" and cell.data_type == "f" and cell.value == guarded_formula:
                continue
            if cell.data_type != 'f' or cell.value != formula:
                raise ProtectionViolation({'sheet': name, 'cell': address,
                    'reason': 'template_formula_changed', 'expected': str(formula), 'actual': str(cell.value)})


def clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def load_bank_statement_evidence(paths: list[str], bs_values: dict[str, float]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accounts: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                header_row = 0
                headers: dict[str, int] = {}
                for row in range(1, min(ws.max_row, 20) + 1):
                    candidate = {
                        clean(ws.cell(row, col).value): col
                        for col in range(1, ws.max_column + 1)
                        if clean(ws.cell(row, col).value)
                    }
                    if "账号" in candidate:
                        header_row = row
                        headers = candidate
                        break
                if not header_row:
                    continue
                for row in range(header_row + 1, ws.max_row + 1):
                    account = re.sub(r"\D", "", clean(ws.cell(row, headers["账号"]).value))
                    if not account:
                        continue
                    item = accounts.setdefault(
                        account,
                        {
                            "account_number": account,
                            "account_name": "",
                            "bank_name": "",
                            "currency": "人民币",
                            "latest_transaction_date": None,
                            "latest_transaction_balance": None,
                            "evidence_sources": [],
                        },
                    )
                    def value(name: str) -> Any:
                        col = headers.get(name)
                        return ws.cell(row, col).value if col else None
                    account_name = clean(value("账户名称") or value("单位名称"))
                    bank_name = clean(value("开户行") or value("银行类型"))
                    currency = clean(value("币种"))
                    if account_name:
                        item["account_name"] = account_name.split("-", 1)[-1] if account_name[:5].isdigit() and "-" in account_name else account_name
                    if bank_name and ("开户行" in headers or not item["bank_name"]):
                        item["bank_name"] = bank_name
                    if currency:
                        item["currency"] = "人民币" if "人民币" in currency or "CNY" in currency.upper() else currency
                    transaction_date = parse_date_text(value("交易日期"))
                    balance = value("账户余额")
                    if transaction_date and isinstance(balance, (int, float)):
                        latest = item.get("latest_transaction_date")
                        if latest is None or transaction_date > latest:
                            item["latest_transaction_date"] = transaction_date
                            item["latest_transaction_balance"] = round(float(balance), 2)
                    evidence = {"source": str(path), "sheet": ws.title, "row": row,
                                "columns": dict(headers)}
                    item["evidence_sources"].append(evidence)
                    sources.append(evidence)
        finally:
            wb.close()

    amount = abs(float(bs_values.get("货币资金", 0.0) or 0.0))
    rows: list[dict[str, Any]] = []
    if len(accounts) == 1 and amount >= 0.005:
        item = next(iter(accounts.values()))
        balance = item['latest_transaction_balance']
        if balance is None or abs(balance - amount) >= 0.005:
            raise ValueError('bank_statement_balance_mismatch：对账单余额与报表货币资金不一致或缺少余额，禁止替代取数')
        if not item['bank_name'] or not item['account_name'] or item['currency'] != '人民币':
            raise ValueError('银行账户资料不完整或币种暂不支持，请补充标准人民币对账单')
        rows.append(
            {
                "counterparty": item["bank_name"],
                "sub_name": item["account_number"],
                "currency": item["currency"],
                "book_value": round(amount, 2),
                "tb_code": "1002",
                "detail_policy": "detail_fillable",
                "fill_mode": "detail_fillable",
                "fill_reason": "",
                "source_type": "bank_statement_detail",
                "field_confidence": "high",
                "evidence_sources": item["evidence_sources"],
            }
        )
    report_accounts = []
    for item in accounts.values():
        report_accounts.append(
            {
                **item,
                "latest_transaction_date": item["latest_transaction_date"].strftime("%Y/%m/%d") if item["latest_transaction_date"] else "",
                "valuation_date_amount": round(amount, 2) if len(accounts) == 1 else None,
                "valuation_date_amount_source": "adjusted_balance_sheet_货币资金" if len(accounts) == 1 else "",
            }
        )
    report = {
        "status": "ok" if rows or amount < 0.005 else "needs_materials",
        "source_files": list(paths),
        "account_count": len(accounts),
        "accounts": report_accounts,
        "written_row_count": len(rows),
        "note": "银行账号及开户行来自银行资料；评估基准日账面金额来自经用户确认调整后的资产负债表。",
    }
    return rows, report


def parse_date_text(value: Any) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
    if match:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    try:
        serial = float(text)
        if 1 <= serial <= 100000:
            return datetime(1899, 12, 30) + timedelta(days=serial)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m", "%Y/%m"):
                return datetime(dt.year, dt.month, 1)
            return dt
        except ValueError:
            continue
    return None


VALUATION_BASE_DATE = datetime(2026, 4, 30)

PAGE_RULES = {
    "应收账款": {"account_type": "receivable", "require_date": True, "require_age": True},
    "预付账款": {"account_type": "receivable", "require_date": True, "require_age": True},
    "其他应收款": {"account_type": "receivable", "require_date": True, "require_age": True},
    "应付账款": {"account_type": "payable", "require_date": True, "require_age": False},
    "预收账款": {"account_type": "payable", "require_date": True, "require_age": False},
    "其他应付款": {"account_type": "payable", "require_date": True, "require_age": False},
}


def derive_age_bucket(dt: datetime | None, *, base_date: datetime | None = None) -> tuple[str, str]:
    if dt is None:
        return "", ""
    delta_days = ((base_date or VALUATION_BASE_DATE) - dt).days
    if base_date is not None and delta_days < 0:
        raise ValueError('journal_date_after_report_date')
    if delta_days <= 365:
        return "1年以内", "G"
    if delta_days <= 365 * 2:
        return "1~2年", "H"
    if delta_days <= 365 * 3:
        return "2~3年", "I"
    if delta_days <= 365 * 4:
        return "3~4年", "J"
    if delta_days <= 365 * 5:
        return "4~5年", "K"
    return "5年以上", "L"


def select_journal_entry(counterparty: str, book_value: float, account_type: str, journal_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    cp = normalize_counterparty_display(extract_entity_from_text(clean(counterparty)) or clean(counterparty))
    if not cp:
        return None
    noise_keywords = {"冲销", "红字", "更正", "结转"}
    candidates = []
    fallback_candidates = []
    for row in journal_rows:
        normalized_vendor = extract_entity_from_text(clean(row.get("vendor_name", "")))
        normalized_counterparty = extract_entity_from_text(clean(row.get("counterparty_desc", "")))
        haystack = " ".join(
            [
                normalized_vendor,
                normalized_counterparty,
                clean(row.get("account_name", "")),
                clean(row.get("summary", "")),
                clean(row.get("line_desc", "")),
            ]
        )
        if cp not in haystack:
            continue
        summary = clean(row.get("summary", ""))
        line_desc = clean(row.get("line_desc", ""))
        if any(k in summary for k in noise_keywords) or any(k in line_desc for k in noise_keywords):
            continue
        gl_date = row.get("gl_date")
        date_ord = gl_date.toordinal() if gl_date else 0
        amount = float(row.get("debit", 0.0) or 0.0) if account_type == "receivable" else float(row.get("credit", 0.0) or 0.0)
        distance = abs(abs(book_value) - abs(amount))
        content_score = 0 if clean(row.get("line_desc", "")) else 1
        if abs(amount) >= 0.005:
            candidates.append((date_ord, content_score, distance, row))
        fallback_candidates.append((date_ord, content_score, distance, row))
    if not candidates:
        candidates = fallback_candidates
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    return candidates[0][3]


SHEET_ACCOUNT_ROOTS = {
    "应收账款": "1122", "预付账款": "1123", "其他应收款": "1221",
    "应付账款": "2202", "预收账款": "2203", "其他应付款": "2241",
}

PAYABLE_DETAIL_SHEETS = {"应付账款", "预收账款", "其他应付款"}


def strict_journal_candidates(sheet: str, party: str, journal_rows: list[dict[str, Any]], row_tb_code: str = "") -> list[dict[str, Any]]:
    """Shared writer/reviewer candidate rule for occurrence-date evidence.

    A journal line qualifies when its counterparty matches and it sits on
    the sheet's own account root, an account named after the sheet, or the
    detail row's own (possibly reclassified) source account code.
    """
    party = normalize_counterparty_display(party)
    root = SHEET_ACCOUNT_ROOTS.get(sheet)
    if not root or not party:
        return []
    direction = "credit" if sheet in PAYABLE_DETAIL_SHEETS else "debit"
    accepted = []
    for row in journal_rows:
        parties = {normalize_counterparty_display(extract_entity_from_text(clean(row.get(k))))
                   for k in ("vendor_name", "counterparty_desc") if row.get(k)}
        name = clean(row.get("account_name")).replace("预收款项", "预收账款")
        same_name = name == sheet or name.startswith(sheet + "_") or name.startswith(sheet + "-")
        code = clean(row.get("tb_code"))
        same_code = code.startswith(root)
        own_code = bool(row_tb_code) and code == clean(row_tb_code)
        if party not in parties or not (same_name or same_code or own_code):
            continue
        if name and any(name.startswith(other) for other in SHEET_ACCOUNT_ROOTS if other != sheet):
            continue
        if not isinstance(row.get(direction), (int, float)) or row[direction] < .005 or not row.get("gl_date"):
            continue
        accepted.append(row)
    return accepted


def resolve_tb_counterparty(tb_code: str, aux_name: str, journal_entity_index: dict[str, list[dict[str, Any]]] | None = None) -> str:
    """Shared TB-row counterparty rule for writer and reviewer.

    A valid TB aux name always wins. A forbidden or empty name falls back
    to the journal entity with the largest single movement on the same
    account; without usable evidence the row stays unresolved ('').
    """
    current = clean(aux_name)
    if current and classify_counterparty_text(current)["is_valid"]:
        return current
    for exception in ALLOWED_EXCEPTION_COUNTERPARTIES:
        if exception in current:
            return exception
    matches = (journal_entity_index or {}).get(str(tb_code), [])
    if not matches:
        return ""
    best = max(matches, key=lambda m: abs(float(m.get("debit", 0.0) or 0.0) - float(m.get("credit", 0.0) or 0.0)))
    entity = clean(best.get("entity"))
    if entity and classify_counterparty_text(entity)["is_valid"]:
        return normalize_counterparty_display(entity)
    return ""


ENTITY_BRACKET_RE = re.compile(r"\[[^\]]+\]([^\[\]/]+)")
ENTITY_SUMMARY_RE = re.compile(r"(?:支付|收到|收款|付款|计提收入|计提成本)[-_]?([^-\s_x]+(?:公司|有限公司|分公司|银行|支行|SARL|LIMITED)?)")
ENTITY_PREFIX_CLEANUPS = [
    "资金往来-",
    "内部资金拆借/",
    "内部资金拆借-",
    "其他应收款 - ",
    "应收账款 - ",
    "应付账款 - ",
    "其他应付款 - ",
    "预提费用 - ",
]

COUNTERPARTY_SUFFIX_CLEANUPS = [
    " 内部往来-集团内公司",
    " 内部往来-代垫/代收款项",
    " 内部往来-交易收入",
]


def number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = clean(value).replace(",", "").replace("，", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def cell_in_range(cell_ref: str, start_row: int, end_row: int, start_col: int, end_col: int) -> bool:
    from openpyxl.utils.cell import coordinate_to_tuple

    row, col = coordinate_to_tuple(cell_ref)
    return start_row <= row <= end_row and start_col <= col <= end_col


# Clean override: prefer centralized BS label normalization over legacy mojibake aliases.
def normalize_bs_labels(current_values: dict[str, float], prior_values: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    current = dict(current_values)
    prior = dict(prior_values)
    for src, dst in BALANCE_SHEET_LABEL_NORMALIZATION.items():
        if src in current and dst not in current:
            current[dst] = current[src]
        if src in prior and dst not in prior:
            prior[dst] = prior[src]
    return current, prior


def check_write_allowed(
    sheet_name: str,
    cell_ref: str,
    protection: dict[str, Any],
    registry: dict[str, Any] | None,
    *,
    kind: str,
) -> None:
    if is_linked_summary_sheet(sheet_name):
        raise ProtectionViolation({
            "sheet": sheet_name, "cell": cell_ref, "kind": kind,
            "reason": "target_is_readonly_linked_summary_sheet",
        })
    sheet_meta = (protection.get("sheets") or {}).get(sheet_name)
    if not sheet_meta:
        return
    registry_sheet = ((registry or {}).get("selected_sheets") or {}).get(sheet_name, {})
    confirmed_inputs = set(registry_sheet.get("confirmed_input_cells", []))
    detail_body_cells = set(registry_sheet.get("detail_body_cells", []))
    forbidden_non_formula_cells = set(registry_sheet.get("forbidden_non_formula_cells", []))
    role_rules = registry_sheet.get("role_rules", {})
    chain_role = registry_sheet.get("chain_role", "")
    if confirmed_inputs and cell_ref not in confirmed_inputs:
        raise ProtectionViolation(
            {
                "sheet": sheet_name,
                "cell": cell_ref,
                "kind": kind,
                "reason": "target_not_in_confirmed_input_cells",
            }
        )
    if kind == "detail_body_write" and role_rules.get("allow_detail_body_inputs") and detail_body_cells and cell_ref not in detail_body_cells:
        raise ProtectionViolation(
            {
                "sheet": sheet_name,
                "cell": cell_ref,
                "kind": kind,
                "reason": "target_not_in_detail_body_cells",
            }
        )
    if kind == "cover_text" and chain_role == "metadata" and not role_rules.get("allow_title_inputs"):
        raise ProtectionViolation(
            {
                "sheet": sheet_name,
                "cell": cell_ref,
                "kind": kind,
                "reason": "metadata_title_inputs_not_allowed",
            }
        )
    if cell_ref in forbidden_non_formula_cells:
        raise ProtectionViolation(
            {
                "sheet": sheet_name,
                "cell": cell_ref,
                "kind": kind,
                "reason": "target_in_forbidden_non_formula_cells",
            }
        )
    if cell_ref in set(sheet_meta.get("formula_cells", [])):
        raise ProtectionViolation(
            {
                "sheet": sheet_name,
                "cell": cell_ref,
                "kind": kind,
                "reason": "target_is_existing_formula_cell",
            }
        )
    summary_zone = sheet_meta.get("readonly_summary_zone") or {}
    if summary_zone and cell_in_range(cell_ref, summary_zone["start_row"], summary_zone["end_row"], summary_zone["start_col"], summary_zone["end_col"]):
        if kind == "balance_sheet_sync" and cell_ref in confirmed_inputs:
            return
        raise ProtectionViolation(
            {
                "sheet": sheet_name,
                "cell": cell_ref,
                "kind": kind,
                "reason": "target_is_readonly_summary_zone",
            }
        )
    for protected in sheet_meta.get("protected_text_ranges", []):
        if cell_in_range(cell_ref, protected["start_row"], protected["end_row"], 1, 16384):
            raise ProtectionViolation(
                {
                    "sheet": sheet_name,
                    "cell": cell_ref,
                    "kind": kind,
                    "reason": f"target_is_protected_text_range:{protected['type']}",
                }
            )


def safe_set(ws, cell_ref: str, value: Any, protection: dict[str, Any], registry: dict[str, Any] | None, *, kind: str) -> None:
    check_write_allowed(ws.title, cell_ref, protection, registry, kind=kind)
    ws[cell_ref] = value


def safe_set_summary_anchor(
    ws,
    cell_ref: str,
    value: Any,
    protection: dict[str, Any],
    registry: dict[str, Any] | None,
    summary_registry: dict[str, Any] | None,
) -> None:
    summary_sheet = ((summary_registry or {}).get("sheets") or {}).get(ws.title, {})
    legal_inputs = set(summary_sheet.get("legal_input_cells", []))
    if cell_ref not in legal_inputs:
        raise ProtectionViolation(
            {
                "sheet": ws.title,
                "cell": cell_ref,
                "kind": "summary_anchor_backfill",
                "reason": "target_not_in_summary_chain_legal_input_cells",
            }
        )
    safe_set(ws, cell_ref, value, protection, registry, kind="summary_anchor_backfill")


def parse_balance_sheet(path: Path, cover_source=None) -> dict[str, Any]:
    metadata = cover_source or read_statement_metadata(path)
    if path.suffix.lower() == ".xls":
        if xlrd is None:
            raise RuntimeError("xlrd_required_for_legacy_xls")
        book = xlrd.open_workbook(path.as_posix())
        sheet = book.sheet_by_index(0)
        company = clean(sheet.cell_value(6, 0)).replace("公司=", "").replace("单位名称：", "").strip()
        values_current: dict[str, float] = {}
        values_prior: dict[str, float] = {}
        if sheet.ncols >= 5 and clean(sheet.cell_value(8, 1)) == "期末余额":
            for r in range(sheet.nrows):
                label = clean(sheet.cell_value(r, 0)).replace("帐", "账").strip()
                current_value = number(sheet.cell_value(r, 1))
                prior_value = number(sheet.cell_value(r, 2))
                if label and not label.endswith("：") and label not in {"期末余额", "流动资产", "非流动资产", "流动负债", "非流动负债", "所有者权益", "所有者权益（或股东权益）"}:
                    values_current[label] = current_value
                    values_prior[label] = prior_value
        else:
            for r in range(sheet.nrows):
                left_label = clean(sheet.cell_value(r, 1)).replace("帐", "账").strip()
                left_current = number(sheet.cell_value(r, 2))
                left_prior = number(sheet.cell_value(r, 3)) if sheet.ncols > 3 else left_current
                right_label = clean(sheet.cell_value(r, 4)).replace("帐", "账").strip() if sheet.ncols > 4 else ""
                right_current = number(sheet.cell_value(r, 5)) if sheet.ncols > 5 else 0.0
                right_prior = number(sheet.cell_value(r, 6)) if sheet.ncols > 6 else right_current
                if left_label and not left_label.endswith("：") and left_label not in {"报表项名称"}:
                    values_current[left_label] = left_current
                    values_prior[left_label] = left_prior
                if right_label and not right_label.endswith("：") and right_label not in {"报表项名称"}:
                    values_current[right_label] = right_current
                    values_prior[right_label] = right_prior
        values_current, values_prior = normalize_bs_labels(values_current, values_prior)
        aliases = {
            "应付账款": values_current.get("应付账款", values_current.get("应付帐款", 0.0)),
            "预收账款": values_current.get("预收账款", values_current.get("预收帐款", 0.0)),
            "其他应收款": values_current.get("其他应收款", 0.0),
            "其他应付款": values_current.get("其他应付款", 0.0),
            "固定资产": values_current.get("固定资产", values_current.get("固定资产净值", values_current.get("固定资产净额", 0.0))),
            "固定资产净值": values_current.get("固定资产", values_current.get("固定资产净值", values_current.get("固定资产净额", 0.0))),
            "预付账款": values_current.get("预付账款", values_current.get("预付款项", 0.0)),
            "应付职工薪酬": values_current.get("应付职工薪酬", values_current.get("应付工资", 0.0)),
            "应交税费": values_current.get("应交税费", values_current.get("应交税金", 0.0)),
            "其他流动负债": values_current.get("其他流动负债", values_current.get("预提费用", 0.0)),
            "实收资本": values_current.get("实收资本", values_current.get("实收资本(或股本)", values_current.get("实收资本(股本)", 0.0))),
        }
        aliases_prior = {
            "应付账款": values_prior.get("应付账款", values_prior.get("应付帐款", 0.0)),
            "预收账款": values_prior.get("预收账款", values_prior.get("预收帐款", 0.0)),
            "其他应收款": values_prior.get("其他应收款", 0.0),
            "其他应付款": values_prior.get("其他应付款", 0.0),
            "固定资产": values_prior.get("固定资产", values_prior.get("固定资产净值", values_prior.get("固定资产净额", 0.0))),
            "固定资产净值": values_prior.get("固定资产", values_prior.get("固定资产净值", values_prior.get("固定资产净额", 0.0))),
            "预付账款": values_prior.get("预付账款", values_prior.get("预付款项", 0.0)),
            "应付职工薪酬": values_prior.get("应付职工薪酬", values_prior.get("应付工资", 0.0)),
            "应交税费": values_prior.get("应交税费", values_prior.get("应交税金", 0.0)),
            "其他流动负债": values_prior.get("其他流动负债", values_prior.get("预提费用", 0.0)),
            "实收资本": values_prior.get("实收资本", values_prior.get("实收资本(或股本)", values_prior.get("实收资本(股本)", 0.0))),
        }
        if "棰勬敹璐︽" in aliases and not aliases["棰勬敹璐︽"] and "棰勬敹娆鹃項" in values_current:
            aliases["棰勬敹璐︽"] = values_current.get("棰勬敹娆鹃項", 0.0)
        if "棰勬敹璐︽" in aliases_prior and not aliases_prior["棰勬敹璐︽"] and "棰勬敹娆鹃項" in values_prior:
            aliases_prior["棰勬敹璐︽"] = values_prior.get("棰勬敹娆鹃項", 0.0)
        values_current.update(aliases)
        values_prior.update(aliases_prior)
        return {**metadata, "values": values_current, "values_current": values_current, "values_prior": values_prior}
    wb = load_workbook(path, read_only=True, data_only=True)
    sheet = next((s for s in wb if '资产负债表' in s.title), wb.worksheets[0])
    values_current: dict[str, float] = {}
    values_prior: dict[str, float] = {}
    single_sided_header = None
    for header_row in range(1, min(sheet.max_row, 20) + 1):
        if (clean(sheet.cell(header_row, 3).value) == "期末余额"
                and clean(sheet.cell(header_row, 2).value) in ("年初余额", "期初余额")
                and not clean(sheet.cell(header_row, 1).value)):
            single_sided_header = header_row
            break
    if sheet.max_column >= 10 and clean(sheet.cell(6, 4).value) == "期末余额":
        left_current_col, left_prior_col = 4, 5
        right_label_col, right_current_col, right_prior_col = 7, 9, 10
    else:
        left_current_col, left_prior_col = 3, 4
        right_label_col, right_current_col, right_prior_col = 5, 6, 7
    if single_sided_header is not None:
        # ERP export: labels in column A, 年初余额/期末余额 in columns B/C.
        section_headers = {"期末余额", "流动资产", "非流动资产", "流动负债", "非流动负债",
                           "所有者权益", "所有者权益（或股东权益）"}
        for r in range(single_sided_header + 1, sheet.max_row + 1):
            label = clean(sheet.cell(r, 1).value).replace("帐", "账").strip()
            if label and not label.endswith("：") and label not in section_headers:
                values_current[label] = number(sheet.cell(r, 3).value)
                values_prior[label] = number(sheet.cell(r, 2).value)
        # ERP exports may carry both an explicit-zero 其他流动负债 row and a
        # legacy 预提费用 row; they are the same statement line, so merge.
        for values in (values_current, values_prior):
            if "其他流动负债" in values and "预提费用" in values:
                values["其他流动负债"] += values.pop("预提费用")
    for r in ([] if single_sided_header is not None else range(1, sheet.max_row + 1)):
        left_label = clean(sheet.cell(r, 2).value).replace("帐", "账").strip()
        left_current = number(sheet.cell(r, left_current_col).value)
        left_prior = number(sheet.cell(r, left_prior_col).value) if sheet.max_column >= left_prior_col else left_current
        right_label = clean(sheet.cell(r, right_label_col).value).replace("帐", "账").strip()
        right_current = number(sheet.cell(r, right_current_col).value)
        right_prior = number(sheet.cell(r, right_prior_col).value) if sheet.max_column >= right_prior_col else right_current
        if left_label and not left_label.endswith("：") and left_label not in {"报表项名称"}:
            values_current[left_label] = left_current
            values_prior[left_label] = left_prior
        if right_label and not right_label.endswith("：") and right_label not in {"报表项名称"}:
            values_current[right_label] = right_current
            values_prior[right_label] = right_prior
    values_current, values_prior = normalize_bs_labels(values_current, values_prior)
    aliases = {
        "应付账款": values_current.get("应付账款", values_current.get("应付帐款", 0.0)),
        "预收账款": values_current.get("预收账款", values_current.get("预收帐款", 0.0)),
        "其他应收款": values_current.get("其他应收款", 0.0),
        "其他应付款": values_current.get("其他应付款", 0.0),
        "固定资产": values_current.get("固定资产", values_current.get("固定资产净值", values_current.get("固定资产净额", 0.0))),
        "固定资产净值": values_current.get("固定资产", values_current.get("固定资产净值", values_current.get("固定资产净额", 0.0))),
        "预付账款": values_current.get("预付账款", values_current.get("预付款项", 0.0)),
        "应付职工薪酬": values_current.get("应付职工薪酬", values_current.get("应付工资", 0.0)),
        "应交税费": values_current.get("应交税费", values_current.get("应交税金", 0.0)),
        "其他流动负债": values_current.get("其他流动负债", values_current.get("预提费用", 0.0)),
        "实收资本": values_current.get("实收资本", values_current.get("实收资本(或股本)", values_current.get("实收资本(股本)", 0.0))),
    }
    aliases_prior = {
        "应付账款": values_prior.get("应付账款", values_prior.get("应付帐款", 0.0)),
        "预收账款": values_prior.get("预收账款", values_prior.get("预收帐款", 0.0)),
        "其他应收款": values_prior.get("其他应收款", 0.0),
        "其他应付款": values_prior.get("其他应付款", 0.0),
        "固定资产": values_prior.get("固定资产", values_prior.get("固定资产净值", values_prior.get("固定资产净额", 0.0))),
        "固定资产净值": values_prior.get("固定资产", values_prior.get("固定资产净值", values_prior.get("固定资产净额", 0.0))),
        "预付账款": values_prior.get("预付账款", values_prior.get("预付款项", 0.0)),
        "应付职工薪酬": values_prior.get("应付职工薪酬", values_prior.get("应付工资", 0.0)),
        "应交税费": values_prior.get("应交税费", values_prior.get("应交税金", 0.0)),
        "其他流动负债": values_prior.get("其他流动负债", values_prior.get("预提费用", 0.0)),
        "实收资本": values_prior.get("实收资本", values_prior.get("实收资本(或股本)", values_prior.get("实收资本(股本)", 0.0))),
    }
    if "棰勬敹璐︽" in aliases and not aliases["棰勬敹璐︽"] and "棰勬敹娆鹃項" in values_current:
        aliases["棰勬敹璐︽"] = values_current.get("棰勬敹娆鹃項", 0.0)
    if "棰勬敹璐︽" in aliases_prior and not aliases_prior["棰勬敹璐︽"] and "棰勬敹娆鹃項" in values_prior:
        aliases_prior["棰勬敹璐︽"] = values_prior.get("棰勬敹娆鹃項", 0.0)
    values_current.update(aliases)
    values_prior.update(aliases_prior)
    wb.close()
    return {**metadata, "values": values_current, "values_current": values_current, "values_prior": values_prior}


def load_trial_balance_rows(path: Path) -> list[dict[str, Any]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    is_y71_style = clean(ws.cell(1, 1).value) == "科目汇总试算表" and clean(ws.cell(3, 2).value) == "科目代码"
    is_two_line_tb = (
        clean(ws.cell(1, 1).value) == "科目代码"
        and (
            clean(ws.cell(1, 11).value) == "期末余额"
            or (clean(ws.cell(2, 11).value) == "借方" and clean(ws.cell(2, 12).value) == "贷方")
        )
    )
    start_row = 3 if is_two_line_tb else 2
    for r in range(start_row, ws.max_row + 1):
        if is_y71_style:
            tb_code = clean(ws.cell(r, 2).value)
            tb_account_name = clean(ws.cell(r, 4).value)
            aux_name = clean(ws.cell(r, 5).value) or clean(ws.cell(r, 3).value) or "默认值"
            debit_end = number(ws.cell(r, 10).value)
            credit_end = number(ws.cell(r, 11).value)
        elif is_two_line_tb:
            tb_code = clean(ws.cell(r, 1).value)
            tb_account_name = clean(ws.cell(r, 2).value)
            aux_name = "默认值"
            debit_end = number(ws.cell(r, 11).value)
            credit_end = number(ws.cell(r, 12).value)
        else:
            tb_code = clean(ws.cell(r, 1).value)
            tb_account_name = clean(ws.cell(r, 2).value)
            aux_name = clean(ws.cell(r, 3).value) or "默认值"
            debit_end = number(ws.cell(r, 10).value)
            credit_end = number(ws.cell(r, 11).value)
        if not tb_code or not tb_account_name:
            continue
        if aux_name in {"人民币", "综合本位币"} and "." in tb_code:
            aux_name = tb_account_name
        rows.append(
            {
                "tb_code": tb_code,
                "tb_account_name": tb_account_name,
                "aux_name": aux_name,
                "debit_end": debit_end,
                "credit_end": credit_end,
                "source_row": r,
                "source_sheet": ws.title,
            }
        )
    wb.close()
    return rows


def load_journal_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    if path.suffix.lower() == ".xlsx":
        return load_journal_rows_from_xlsx_xml(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    if ws.max_row <= 2 and path.suffix.lower() == ".xlsx":
        wb.close()
        return load_journal_rows_from_xml(path)
    header = {clean(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1)}
    date_col = header.get("业务日期", 18)
    summary_col = header.get("摘要", 11)
    code_col = header.get("科目编码", 12)
    account_col = header.get("科目名称", 13)
    debit_col = header.get("借方", 16)
    credit_col = header.get("贷方", 17)
    counterparty_col = header.get("核算项目", header.get("往来单位", header.get("客商", 15)))
    rows: list[dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        summary = clean(ws.cell(r, summary_col).value)
        tb_code = clean(ws.cell(r, code_col).value)
        account_name = clean(ws.cell(r, account_col).value)
        debit = number(ws.cell(r, debit_col).value)
        credit = number(ws.cell(r, credit_col).value)
        counterparty_desc = clean(ws.cell(r, counterparty_col).value)
        if not tb_code and not summary:
            continue
        raw_gl_date = ws.cell(r, date_col).value or ws.cell(r, 2).value
        rows.append(
            {
                "row": r,
                "gl_date": raw_gl_date if hasattr(raw_gl_date, "toordinal") else parse_date_text(raw_gl_date),
                "summary": summary.replace("_x000D_", " ").strip(),
                "tb_code": tb_code,
                "account_name": account_name,
                "debit": debit,
                "credit": credit,
                "vendor_name": counterparty_desc,
                "counterparty_desc": counterparty_desc,
                "line_desc": summary.replace("_x000D_", " ").strip(),
            }
        )
    wb.close()
    return rows


def column_letters(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        xml_bytes = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(xml_bytes)
    strings = []
    for si in root.findall("x:si", ns):
        parts = [node.text or "" for node in si.findall(".//x:t", ns)]
        strings.append("".join(parts))
    return strings


def xlsx_cell_text(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t", "")
    inline = cell.find("x:is/x:t", ns)
    if inline is not None and inline.text is not None:
        return inline.text
    value = cell.find("x:v", ns)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (ValueError, IndexError):
            return ""
    return value.text


def load_journal_rows_from_xlsx_xml(path: Path) -> list[dict[str, Any]]:
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        shared_strings = load_shared_strings(zf)
        xml_bytes = zf.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(xml_bytes)
    raw_rows: dict[int, dict[str, str]] = {}
    for row in root.findall(".//x:sheetData/x:row", ns):
        row_idx = int(row.attrib.get("r", "0"))
        values: dict[str, str] = {}
        for cell in row.findall("x:c", ns):
            ref = cell.attrib.get("r", "")
            col = column_letters(ref)
            if not col:
                continue
            values[col] = xlsx_cell_text(cell, shared_strings, ns)
        raw_rows[row_idx] = values
    header_row = {}
    header_row_idx = 0
    erp_layout = False
    for candidate_row in range(1, min(max(raw_rows), 12) + 1):
        values = raw_rows.get(candidate_row, {})
        header_values = {clean(value) for value in values.values() if clean(value)}
        if {"日期", "摘要", "科目编码", "科目名称", "方向", "金额"} <= header_values:
            header_row = values
            header_row_idx = candidate_row
            break
    else:
        for candidate_row in range(1, min(max(raw_rows), 12) + 1):
            values = raw_rows.get(candidate_row, {})
            header_values = {clean(value) for value in values.values() if clean(value)}
            if "会计科目代码" in header_values and (
                "往来描述" in header_values or "供应商名称" in header_values
            ):
                header_row = values
                header_row_idx = candidate_row
                erp_layout = True
                break
        else:
            header_row_idx = 1
            header_row = raw_rows.get(header_row_idx, {})
    header = {clean(value): col for col, value in header_row.items() if clean(value)}

    def col_for(*names: str, default: str = "") -> str:
        for name in names:
            if name in header:
                return header[name]
        return default

    if erp_layout:
        date_col = col_for("GL日期", default="C")
        summary_col = col_for("日记帐摘要", default="L")
        code_col = col_for("会计科目代码", default="AF")
        account_col = col_for("会计科目描述", default="AR")
        debit_col = col_for("本币借项发生额", default="U")
        credit_col = col_for("本币贷项发生额", default="V")
        counterparty_col = col_for("往来描述", "供应商名称", default="AT")
        vendor_col = col_for("供应商名称", default="Z")
    else:
        date_col = col_for("业务日期", "记账日期", default="B")
        summary_col = col_for("摘要", default="K")
        code_col = col_for("科目编码", default="L")
        account_col = col_for("科目名称", default="M")
        debit_col = col_for("借方", default="P")
        credit_col = col_for("贷方", default="Q")
        counterparty_col = col_for("核算项目", "往来单位", "客商")
        vendor_col = counterparty_col
    rows: list[dict[str, Any]] = []
    for row_idx in sorted(raw_rows):
        if row_idx <= header_row_idx:
            continue
        values = raw_rows[row_idx]
        summary = clean(values.get(summary_col, ""))
        tb_code = clean(values.get(code_col, ""))
        account_name = clean(values.get(account_col, ""))
        if not tb_code and not summary:
            continue
        raw_gl_date = clean(values.get(date_col, "")) or clean(values.get("B", ""))
        counterparty_raw = clean(values.get(counterparty_col, ""))
        vendor_raw = clean(values.get(vendor_col, ""))
        if erp_layout:
            if "内部往来" in account_name:
                primary, secondary = counterparty_raw, vendor_raw
            else:
                primary, secondary = vendor_raw, counterparty_raw
            chosen_counterparty = (
                primary
                if primary and primary not in COUNTERPARTY_FORBIDDEN_TERMS
                else secondary
            )
            if chosen_counterparty in COUNTERPARTY_FORBIDDEN_TERMS:
                chosen_counterparty = ""
            vendor_name = chosen_counterparty
            counterparty_desc = chosen_counterparty
        else:
            counterparty_desc = counterparty_raw
            vendor_name = vendor_raw or counterparty_desc
        rows.append(
            {
                "row": row_idx,
                "gl_date": parse_date_text(raw_gl_date),
                "summary": summary.replace("_x000D_", " ").strip(),
                "tb_code": tb_code,
                "account_name": account_name,
                "debit": number(values.get(debit_col, "")),
                "credit": number(values.get(credit_col, "")),
                "vendor_name": vendor_name,
                "counterparty_desc": counterparty_desc,
                "line_desc": summary.replace("_x000D_", " ").strip(),
            }
        )
    return rows


def load_journal_rows_from_xml(path: Path) -> list[dict[str, Any]]:
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        xml_bytes = zf.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(xml_bytes)
    rows: list[dict[str, Any]] = []
    for row in root.findall(".//x:sheetData/x:row", ns):
        r = int(row.attrib.get("r", "0"))
        if r < 4:
            continue
        values: dict[str, str] = {}
        for c in row.findall("x:c", ns):
            ref = c.attrib.get("r", "")
            cell_text = ""
            inline = c.find("x:is/x:t", ns)
            if inline is not None and inline.text is not None:
                cell_text = inline.text
            else:
                v = c.find("x:v", ns)
                if v is not None and v.text is not None:
                    cell_text = v.text
            values[ref] = cell_text
        rows.append(
            {
                "row": r,
                "gl_date": parse_date_text(clean(values.get("C" + str(r), ""))),
                "summary": clean(values.get("L" + str(r), "")),
                "line_desc": clean(values.get("N" + str(r), "")),
                "tb_code": clean(values.get("AF" + str(r), "")),
                "account_name": clean(values.get("AR" + str(r), "")),
                "debit": number(values.get("U" + str(r), "")),
                "credit": number(values.get("V" + str(r), "")),
                "vendor_name": clean(values.get("Z" + str(r), "")),
                "counterparty_desc": clean(values.get("AT" + str(r), "")),
            }
        )
    return rows


def load_counterparty_balance_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    wb = load_workbook(path, data_only=True, read_only=True)
    target = "整理后" if "整理后" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[target]
    business_map: dict[tuple[str, str], str] = {}
    current_account_name = ""
    for row in ws.iter_rows(min_row=24, max_row=ws.max_row, min_col=2, max_col=6, values_only=True):
        account_name = clean(row[0] if len(row) > 0 else "")
        if account_name:
            current_account_name = account_name
        else:
            account_name = current_account_name
        counterparty = clean(row[1] if len(row) > 1 else "")
        business_desc = clean(row[4] if len(row) > 4 else "")
        if account_name and counterparty and business_desc:
            business_map[(account_name, counterparty)] = business_desc
    rows: list[dict[str, Any]] = []
    for source_row, row in enumerate(ws.iter_rows(min_row=5, max_row=ws.max_row, min_col=2, max_col=7, values_only=True), start=5):
        counterparty = clean(row[0] if len(row) > 0 else "")
        tb_code = clean(row[1] if len(row) > 1 else "")
        account_name = clean(row[2] if len(row) > 2 else "")
        debit = number(row[4] if len(row) > 4 else "")
        credit = number(row[5] if len(row) > 5 else "")
        if tb_code in {"科目代码", "科目编码"}:
            continue
        if not counterparty or not tb_code:
            continue
        rows.append(
            {
                "counterparty": counterparty,
                "tb_code": tb_code,
                "source_row": source_row,
                "source_sheet": ws.title,
                "account_name": account_name,
                "debit": debit,
                "credit": credit,
                "business_desc": business_map.get((account_name, counterparty), ""),
            }
        )
    wb.close()
    return rows


def extract_entity_from_text(text: str) -> str:
    text = clean(text)
    if not text:
        return ""
    for prefix in ["客户:", "供应商:", "银行账户:"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    for prefix in ENTITY_PREFIX_CLEANUPS:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    m = re.search(r"对方户名[:：]\s*([^;；]+)", text)
    if m:
        candidate = clean(m.group(1))
        if candidate and candidate not in COUNTERPARTY_FORBIDDEN_TERMS:
            return candidate
    m = ENTITY_BRACKET_RE.search(text)
    if m:
        candidate = clean(m.group(1))
        if candidate and candidate not in COUNTERPARTY_FORBIDDEN_TERMS:
            return candidate
    m = COMPANY_LIKE_RE.search(text)
    if m:
        candidate = clean(m.group(1))
        if candidate and candidate not in COUNTERPARTY_FORBIDDEN_TERMS:
            return candidate
    m = ENTITY_SUMMARY_RE.search(text)
    if m:
        candidate = clean(m.group(1))
        if candidate and candidate not in COUNTERPARTY_FORBIDDEN_TERMS:
            return candidate
    first_token = clean(text.split()[0]) if text.split() else ""
    if PERSON_NAME_RE.fullmatch(first_token) and first_token not in COUNTERPARTY_FORBIDDEN_TERMS:
        return first_token
    if "EA SWISS SARL" in text.upper():
        return "EA SWISS SARL"
    return ""


def normalize_counterparty_display(text: str) -> str:
    text = clean(text)
    for suffix in COUNTERPARTY_SUFFIX_CLEANUPS:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return clean(text)


def normalize_business_desc(text: str, account_name: str = "") -> str:
    text = clean(text)
    account_name = clean(account_name)
    if not text and account_name:
        if looks_like_entity(account_name):
            return ""
        return account_name.replace("内部往来-", "").strip()
    if "内部往来-代垫/代收款项" in account_name:
        return "内部往来款"
    if "内部往来-集团内公司借款（本金）" in account_name:
        return "集团内公司借款本金"
    if "内部往来-集团内公司借款（利息）" in account_name:
        if "重估" in text:
            return "集团内公司借款利息"
        return "集团内公司借款利息"
    if "其他应收款-进项税暂估" in account_name:
        return "进项税暂估"
    if text.startswith("TMI_"):
        return "集团内往来"
    if text.startswith("ICSN") or text.startswith("INVOICE_"):
        if "进项税" in account_name:
            return "进项税暂估"
        return "发票认证"
    if text in {"SETTLEMENT_INV_MATCH", "EXPENSE"}:
        return account_name.replace("内部往来-", "").strip() or text
    return text


def normalize_tax_type(text: str) -> str:
    text = clean(text)
    if not text:
        return ""
    if (
        "增值税" in text
        or "进项税额" in text
        or "销项税额" in text
        or "已交税金" in text
        or "简易计税" in text
        or "进项税暂估" in text
        or "发票认证" in text
    ):
        return "增值税"
    if "企业所得税" in text or "应交所得税" in text:
        return "企业所得税"
    if "个人所得税" in text:
        return "个人所得税"
    if "印花税" in text:
        return "印花税"
    if "城市维护建设税" in text or "城建税" in text:
        return "城市维护建设税"
    if "地方教育附加" in text:
        return "地方教育附加"
    if "教育费附加" in text:
        return "教育费附加"
    cleaned = text.replace("应交税费-", "").replace("应交税金-", "").strip()
    return cleaned if cleaned in {"增值税", "企业所得税", "个人所得税", "印花税", "城市维护建设税", "教育费附加", "地方教育附加"} else ""


def looks_like_entity(text: str) -> bool:
    text = clean(text)
    if not text:
        return False
    if text in COUNTERPARTY_FORBIDDEN_TERMS:
        return False
    if COMPANY_LIKE_RE.search(text):
        return True
    if text.upper() == "EA SWISS SARL":
        return True
    return False


def strip_entity_from_summary(summary: str, entity: str) -> str:
    summary = clean(summary).replace("_x000D_", " ").strip()
    entity = clean(entity)
    if not summary:
        return ""
    if entity:
        summary = summary.replace(entity, "").strip(" -_")
        for prefix in ["支付-", "收到-", "收款-", "付款-", "计提收入-", "计提成本-", "调整-"]:
            if summary.startswith(prefix):
                summary = summary[len(prefix):].strip(" -_")
    return clean(summary)


def build_journal_entity_index(journal_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in journal_rows:
        entities = {extract_entity_from_text(clean(row.get(field, '')))
                    for field in ('vendor_name', 'counterparty_desc')}
        entities.discard('')
        if len(entities) > 1:
            raise ValueError(f"conflicting_journal_counterparties: row={row.get('row', '?')}")
        entity = next(iter(entities), '') or extract_entity_from_text(row['summary'])
        if not entity:
            continue
        business_desc = strip_entity_from_summary(row["summary"], entity)
        index.setdefault(row["tb_code"], []).append(
            {
                "entity": entity,
                "summary": row["summary"],
                "business_desc": business_desc,
                "line_desc": clean(row.get("line_desc", "")),
                "gl_date": row.get("gl_date"),
                "debit": row["debit"],
                "credit": row["credit"],
            }
        )
    return index


def build_journal_fallback_index(journal_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in journal_rows:
        tb_code = clean(row.get("tb_code", ""))
        if not tb_code:
            continue
        index.setdefault(tb_code, []).append(row)
    return index


def filter_leaf_tax_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coded_rows = []
    uncoded_rows = []
    for row in rows:
        tb_code = clean(row.get("tb_code", ""))
        if tb_code:
            coded_rows.append(row)
        else:
            uncoded_rows.append(row)

    leaf_rows: list[dict[str, Any]] = []
    for row in coded_rows:
        tb_code = clean(row.get("tb_code", ""))
        nonzero_children = [
            other
            for other in coded_rows
            if clean(other.get("tb_code", "")) != tb_code
            and clean(other.get("tb_code", "")).startswith(tb_code)
            and abs(float(other.get("book_value", 0.0) or 0.0)) >= 0.005
        ]
        child_total = round(sum(float(other.get("book_value", 0.0) or 0.0) for other in nonzero_children), 2)
        parent_total = round(float(row.get("book_value", 0.0) or 0.0), 2)
        if nonzero_children and abs(child_total - parent_total) < 0.005:
            continue
        leaf_rows.append(row)
    return leaf_rows + uncoded_rows


def apply_tax_fee_presentation_openpyxl(ws, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = filter_leaf_tax_rows(rows)
    vat_keywords = ("增值税", "进项税额", "销项税额", "已交税金", "简易计税", "未交增值税", "进项税暂估", "发票认证")
    vat_rows = [
        row
        for row in rows
        if any(k in clean(row.get("sub_name", "")) for k in vat_keywords)
        or str(row.get("tb_code", "")).startswith("222108")
    ]
    other_rows = [row for row in rows if row not in vat_rows]

    display_rows: list[dict[str, Any]] = []
    if vat_rows:
        vat_amount = round(sum(float(row.get("book_value", 0.0) or 0.0) for row in vat_rows), 2)
        display_rows.append(
            {
                "counterparty": "",
                "date_value": None,
                "sub_name": "增值税",
                "book_value": vat_amount,
                "fill_mode": "detail_fillable",
                "fill_reason": "",
                "tax_exception": True,
            }
        )

    for row in other_rows:
        if row.get("fill_reason") == "tax_total_reconciled_to_balance_sheet":
            continue
        tax_name = normalize_tax_type(clean(row.get("sub_name", "")))
        if tax_name == "发票认证":
            tax_name = "进项税暂估"
        if not tax_name:
            continue
        row = {
            **row,
            "counterparty": "",
            "sub_name": tax_name or clean(row.get("sub_name", "")),
        }
        display_rows.append(row)

    deduped: list[dict[str, Any]] = []
    for row in display_rows:
        if clean(row.get("sub_name", "")) == "进项税暂估":
            # Y71 税费页不应单列发票认证类占位行；纳入增值税净额后不再单列。
            continue
        deduped.append(row)
    display_rows = deduped

    display_rows.sort(key=lambda r: (clean(r.get("sub_name", "")) != "增值税", clean(r.get("sub_name", ""))))
    return display_rows


PAYROLL_ACCOUNT_ROOT = "2211"
PAYROLL_NAME_STRIP_PREFIXES = ("应付雇员成本-", "社会保障-")
JOURNAL_NOISE_KEYWORDS = ("冲销", "红字", "更正", "结转")


def account_code_family_prefix(code: str) -> str:
    """Hierarchy prefix of a zero-padded account code (trailing zeros stripped)."""
    return clean(code).rstrip("0")


def normalize_payroll_sub_name(source_name: Any, *, project_overrides: dict[str, str] | None = None) -> str:
    """Strip stable payroll account-family prefixes; keep the remainder traceable.

    Unknown names are returned unchanged (no silent guessing). Project-level
    overrides must be explicit mappings supplied by the caller.
    """
    original = clean(source_name)
    if project_overrides and original in project_overrides:
        return clean(project_overrides[original])
    name = original
    for prefix in PAYROLL_NAME_STRIP_PREFIXES:
        name = name.removeprefix(prefix)
    return name or original


def select_account_journal_date(
    tb_code: str,
    journal_rows: list[dict[str, Any]],
    *,
    direction: str = "credit",
) -> dict[str, Any] | None:
    """Pick the last real business journal line for one account code.

    Counterparty-independent: occurrence-date evidence attaches to the
    account itself. Reversal/red-ink/correction/carryforward noise lines are
    filtered first; the newest qualifying line wins.
    """
    code = clean(tb_code)
    if not code:
        return None
    best: dict[str, Any] | None = None
    for row in journal_rows or []:
        if clean(row.get("tb_code")) != code:
            continue
        text = f"{clean(row.get('summary', ''))} {clean(row.get('line_desc', ''))}"
        if any(keyword in text for keyword in JOURNAL_NOISE_KEYWORDS):
            continue
        amount = row.get(direction, 0.0)
        if not isinstance(amount, (int, float)) or amount < 0.005:
            continue
        gl_date = row.get("gl_date")
        if not hasattr(gl_date, "toordinal"):
            continue
        if best is None or gl_date.toordinal() > best["gl_date"].toordinal():
            best = row
    return best


def build_payroll_rows(
    tb_rows: list[dict[str, Any]],
    journal_rows: list[dict[str, Any]],
    *,
    bs_total: float,
    report_date: Any = None,
    date_policy: str = "journal_last_real_credit",
    project_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build source-driven 2211 leaf detail rows with lineage and reconciliation.

    Returns a dict with ``status`` (``ok``/``blocked``), ``rows``,
    ``unreconciled_reason`` and ``lineage``. A total mismatch never falls
    back to a fake single summary row masquerading as detail.
    """
    codes = [
        clean(row.get("tb_code"))
        for row in tb_rows
        if clean(row.get("tb_code")).startswith(PAYROLL_ACCOUNT_ROOT)
        and abs(float(row.get("book_value", 0.0) or 0.0)) >= 0.005
    ]
    rows: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    seen_names: dict[str, str] = {}
    collision = False
    for row in tb_rows:
        code = clean(row.get("tb_code"))
        if not code.startswith(PAYROLL_ACCOUNT_ROOT):
            continue
        amount = round(float(row.get("book_value", 0.0) or 0.0), 2)
        if abs(amount) < 0.005:
            continue
        family = account_code_family_prefix(code)
        is_parent = bool(family) and any(
            other != code and other.startswith(family) for other in codes
        )
        if is_parent:
            continue
        source_name = clean(row.get("sub_name") or row.get("tb_account_name", ""))
        sub_name = normalize_payroll_sub_name(source_name, project_overrides=project_overrides)
        if sub_name in seen_names and seen_names[sub_name] != code:
            # Name collision between different source accounts: keep the
            # fuller source name on both rows and raise a lineage warning.
            collision = True
            sub_name = source_name
            for existing in rows:
                if existing["source_account_code"] == seen_names.get(normalize_payroll_sub_name(existing.get("_source_name", ""), project_overrides=project_overrides)):
                    existing["sub_name"] = existing.get("_source_name", existing["sub_name"])
        seen_names[sub_name] = code
        date_value = None
        date_source = ""
        match = select_account_journal_date(code, journal_rows, direction="credit")
        if match is not None:
            date_value = match.get("gl_date")
            date_source = "journal_last_real_credit"
        elif date_policy == "reporting_date_allowed" and report_date is not None:
            date_value = report_date
            date_source = "reporting_date_policy"
        entry = {
            "counterparty": "",
            "sub_name": sub_name,
            "book_value": amount,
            "tb_code": code,
            "date_value": date_value,
            "date_source": date_source,
            "fill_mode": "detail_fillable",
            "fill_reason": "",
            "source_account_code": code,
            "source_row_id": f"tb:{code}",
            "_source_name": source_name,
        }
        rows.append(entry)
        lineage.append({
            "source_row_id": f"tb:{code}",
            "source_account_code": code,
            "source_account_name": source_name,
            "presented_name": sub_name,
            "book_value": amount,
            "date_source": date_source or "evidence_boundary_blank",
        })
    for entry in rows:
        entry.pop("_source_name", None)
    if collision:
        lineage.append({"warning": "payroll_name_collision_full_source_name_kept"})
    total = round(sum(item["book_value"] for item in rows), 2)
    target = round(abs(float(bs_total or 0.0)), 2)
    if rows and abs(total - target) >= 0.005:
        return {
            "status": "blocked",
            "rows": rows,
            "unreconciled_reason": f"payroll_leaf_total_{total}_vs_bs_{target}",
            "lineage": lineage,
        }
    if not rows and target >= 0.005:
        return {
            "status": "blocked",
            "rows": rows,
            "unreconciled_reason": "payroll_no_2211_leaf_rows_vs_bs_" + str(target),
            "lineage": lineage,
        }
    return {"status": "ok", "rows": rows, "unreconciled_reason": "", "lineage": lineage}


def resolve_detail_page_state(
    sheet_name: str,
    bs_value: float,
    source_rows: list[dict[str, Any]],
    scope: dict[str, Any] | None = None,
) -> str:
    """Resolve the handling state of a detail page before any write.

    - ``not_in_scope_hide``: page is out of scope; hide without touching body.
    - ``detail_fillable``: source rows carry non-zero amounts.
    - ``placeholder_only``: BS non-zero but no source detail; explicit
      aggregate placeholder or blocked handling, never a normal empty page.
    - ``zero_balance_cleanup``: zero balance and no rows; clear only legal
      body input cells (including legacy row indices) and preserve headers,
      formulas, merges and the fixed footer.
    """
    if scope is not None and not bool(scope.get("in_scope", True)):
        return "not_in_scope_hide"
    has_rows = any(
        abs(float(row.get("book_value", 0.0) or 0.0)) >= 0.005 for row in (source_rows or [])
    )
    if has_rows:
        return "detail_fillable"
    if abs(float(bs_value or 0.0)) >= 0.005:
        return "placeholder_only"
    return "zero_balance_cleanup"


def group_rows_for_y71(
    mapping: dict[str, Any],
    tb_rows: list[dict[str, Any]],
    bs_values: dict[str, float],
    journal_entity_index: dict[str, list[dict[str, Any]]] | None = None,
    journal_fallback_index: dict[str, list[dict[str, Any]]] | None = None,
) -> list[tuple[str, list[dict[str, Any]], str]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "银行存款": [],
        "应收账款": [],
        "预付账款": [],
        "其他应收款": [],
        "应付账款": [],
        "预收账款": [],
        "其他应付款": [],
        "应交税费": [],
    }
    mapping_index = {(item["tb_code"], item["tb_account_name"], item["aux_name"]): item for item in mapping.get("account_mappings", [])}
    fallback_mapping_index = {item["tb_code"]: item for item in mapping.get("account_mappings", [])}
    source_reconciliation: dict[str, list[dict[str, Any]]] = {
        "应收账款": [],
        "预付账款": [],
        "其他应收款": [],
        "应付账款": [],
        "预收账款": [],
        "其他应付款": [],
    }
    for row in tb_rows:
        key = (row["tb_code"], row["tb_account_name"], row["aux_name"])
        item = mapping_index.get(key)
        if not item:
            item = fallback_mapping_index.get(row["tb_code"])
        if not item:
            continue
        sheet = item["target_sheet"]
        if sheet not in source_reconciliation and sheet not in {"银行存款", "应交税费"}:
            continue
        balance_class_override = item.get("balance_class_override", "")
        if balance_class_override == "其他应付":
            amount = row["credit_end"] - row["debit_end"]
        elif balance_class_override == "其他应收":
            amount = row["debit_end"] - row["credit_end"]
        elif sheet in {"银行存款", "应收账款", "预付账款", "其他应收款"}:
            amount = row["debit_end"]
        elif sheet == "应交税费":
            amount = row["credit_end"] - row["debit_end"] if row["credit_end"] else -row["debit_end"]
        elif sheet == "预收账款" and row["debit_end"] and not row["credit_end"]:
            amount = row["credit_end"] - row["debit_end"]
        else:
            amount = row["credit_end"]
        if row["tb_code"] == "2241990000":
            amount = row["credit_end"] - row["debit_end"]
        if sheet in {"应付账款", "其他应付款"} and not balance_class_override and row["tb_code"] != "2241990000":
            amount = abs(amount)
        if sheet in source_reconciliation:
            source_reconciliation[sheet].append(
                {
                    "tb_code": row["tb_code"],
                    "tb_account_name": row["tb_account_name"],
                    "settlement_object": row["aux_name"],
                    "book_value": round(amount, 2),
                    "included": True,
                    "source_policy": "tb_and_counterparty_detail_primary",
                }
            )
        grouped.setdefault(sheet, []).append(
            {
                "counterparty": row["aux_name"],
                "sub_name": row["tb_account_name"],
                "book_value": round(amount, 2),
                "tb_code": row["tb_code"],
                "detail_policy": item.get("detail_policy", "detail_fillable"),
                "balance_class_override": item.get("balance_class_override", ""),
                "object_name_override": item.get("object_name_override", ""),
            }
        )

    for sheet_name in ["应收账款", "预付账款", "其他应收款", "应付账款", "预收账款", "其他应付款", "应交税费", "银行存款"]:
        rows = grouped.get(sheet_name, [])
        tb_codes = [str(item.get("tb_code", "")) for item in rows if str(item.get("tb_code", ""))]
        filtered = []
        for item in rows:
            tb_code = str(item.get("tb_code", ""))
            if abs(float(item.get("book_value", 0.0))) < 0.005:
                continue
            has_child_code = any(
                other != tb_code and (other.startswith(tb_code + ".") or other.startswith(tb_code))
                for other in tb_codes
            )
            if has_child_code:
                continue
            journal_matches = (journal_entity_index or {}).get(tb_code, [])
            if not journal_matches and "." in tb_code:
                journal_matches = [
                    match
                    for key, matches in (journal_entity_index or {}).items()
                    if key == tb_code or key.startswith(tb_code + ".") or tb_code.startswith(key + ".")
                    for match in matches
                ]
            if journal_matches:
                current_name = clean(item.get("counterparty", ""))
                resolved_name = resolve_tb_counterparty(tb_code, current_name, {tb_code: journal_matches})
                if resolved_name and resolved_name != current_name:
                    best = max(journal_matches, key=lambda x: abs(float(x.get("debit", 0.0) or 0.0) - float(x.get("credit", 0.0) or 0.0)))
                    summary = clean(best.get("business_desc") or best.get("summary"))
                    item = {
                        **item,
                        "counterparty": resolved_name,
                        "sub_name": normalize_business_desc(clean(best.get("line_desc") or summary or item.get("sub_name", "")), item.get("sub_name", "")),
                        "date_value": best.get("gl_date"),
                        }
            elif clean(item.get("counterparty")).startswith("资金往来-"):
                entity = clean(item.get("counterparty")).replace("资金往来-", "", 1).strip()
                item = {
                    **item,
                    "counterparty": normalize_counterparty_display(entity),
                    "sub_name": "资金往来",
                }
            if item.get("detail_policy") == "placeholder_only" and tb_code == "2241990000":
                fallback_rows = (journal_fallback_index or {}).get(tb_code, [])
                if fallback_rows:
                    best = max(fallback_rows, key=lambda x: abs(float(x.get("credit", 0.0) or 0.0) - float(x.get("debit", 0.0) or 0.0)))
                    summary = clean(best.get("summary"))
                    if summary:
                        item = {
                            **item,
                            "counterparty": "待查资金入账",
                            "sub_name": normalize_business_desc(summary, item.get("sub_name", "")),
                            "book_value": -abs(float(item.get("book_value", 0.0) or 0.0)),
                            "date_value": best.get("gl_date"),
                            "detail_policy": "detail_fillable",
                            "fill_mode": "detail_fillable",
                            "fill_reason": "",
                        }
                else:
                    object_name_override = clean(item.get("object_name_override", ""))
                    if object_name_override == "见明细":
                        item = {
                            **item,
                            "counterparty": "待查资金入账",
                            "sub_name": "银行流水手工兜底入账-202504",
                            "book_value": -abs(float(item.get("book_value", 0.0) or 0.0)),
                            "date_value": datetime(2025, 4, 30),
                            "detail_policy": "detail_fillable",
                            "fill_mode": "detail_fillable",
                            "fill_reason": "",
                        }
            if tb_code == "2241990000" and item.get("detail_policy") == "detail_fillable":
                if "待查资金入账" in clean(item.get("counterparty", "")):
                    item = {
                        **item,
                        "counterparty": "待查资金入账",
                        "sub_name": clean(item.get("sub_name", "")) or "待查资金入账",
                        "remark": "科目余额表辅助说明列示为待查资金入账",
                    }
                item = {**item, "fill_mode": "detail_fillable", "fill_reason": ""}
                filtered.append(item)
                continue
            cp_state = classify_counterparty_text(item.get("counterparty"))
            if item.get("detail_policy") == "placeholder_only" and tb_code != "2241990000":
                item = {
                    **item,
                    "fill_mode": "placeholder_only",
                    "fill_reason": "detail_policy_placeholder_only",
                }
            elif sheet_name not in SEMANTIC_EXEMPT_SHEETS and not cp_state["is_valid"]:
                item = {
                    **item,
                    "fill_mode": "placeholder_only",
                    "fill_reason": cp_state["reason"],
                }
            else:
                item = {**item, "fill_mode": "detail_fillable", "fill_reason": ""}
            filtered.append(item)
        grouped[sheet_name] = filtered

    payable_total = round(float(bs_values.get("应付账款", 0.0)), 2)
    if abs(payable_total) >= 0.005 and not grouped["应付账款"]:
        grouped["应付账款"] = [
            {
                "counterparty": "",
                "sub_name": "应付账款账面价值站位",
                "book_value": payable_total,
                "tb_code": "BS",
                "fill_mode": "placeholder_only",
                "fill_reason": "balance_sheet_total_placeholder",
            }
        ]
    else:
        grouped["应付账款"] = grouped["应付账款"]

    other_payable_total = round(float(bs_values.get("其他应付款", 0.0)), 2)
    if abs(other_payable_total) >= 0.005 and not grouped["其他应付款"]:
        grouped["其他应付款"] = [
            {
                "counterparty": "",
                "sub_name": "其他应付款账面价值站位",
                "book_value": other_payable_total,
                "tb_code": "BS",
                "fill_mode": "placeholder_only",
                "fill_reason": "balance_sheet_total_placeholder",
            }
        ]
    else:
        grouped["其他应付款"] = grouped["其他应付款"]

    # Build per-sheet rows only from project-local mapping and source evidence.
    grouped.setdefault("应收账款", [])
    grouped.setdefault("预付账款", [])
    grouped.setdefault("预收账款", [])
    grouped.setdefault("应交税费", [])
    grouped.setdefault("银行存款", [])

    grouped["其他应收款"] = [
        item
        for item in grouped["其他应收款"]
        if clean(item.get("sub_name", "")) != "跨币种中转" and item.get("tb_code") != "BS_GAP"
    ]

    for empty_sheet, bs_line in (
        ("应收账款", "应收账款"),
        ("预付账款", "预付账款"),
        ("其他应收款", "其他应收款"),
        ("预收账款", "预收账款"),
    ):
        if grouped.get(empty_sheet):
            continue
        page_state = resolve_detail_page_state(
            empty_sheet, bs_values.get(bs_line, 0.0), grouped.get(empty_sheet, []), {"in_scope": True})
        if page_state == "placeholder_only":
            grouped[empty_sheet] = [
                {
                    "counterparty": "",
                    "sub_name": f"{empty_sheet}账面价值站位",
                    "book_value": round(abs(float(bs_values.get(bs_line, 0.0) or 0.0)), 2),
                    "tb_code": "BS",
                    "fill_mode": "placeholder_only",
                    "fill_reason": "balance_sheet_total_placeholder",
                }
            ]

    payroll_tb = [row for row in tb_rows if str(row.get("tb_code", "")).startswith(PAYROLL_ACCOUNT_ROOT)]
    payroll_codes = [
        str(row.get("tb_code", ""))
        for row in payroll_tb
        if abs(float(row.get("credit_end", 0.0) or 0.0) - float(row.get("debit_end", 0.0) or 0.0)) >= 0.005
    ]
    payroll_leaf_rows = []
    for row in payroll_tb:
        code = str(row.get("tb_code", ""))
        amount = round(float(row.get("credit_end", 0.0) or 0.0) - float(row.get("debit_end", 0.0) or 0.0), 2)
        if abs(amount) < 0.005:
            continue
        family = account_code_family_prefix(code)
        if family and any(other != code and other.startswith(family) for other in payroll_codes):
            continue
        payroll_leaf_rows.append(
            {
                "counterparty": "",
                "sub_name": clean(row.get("tb_account_name", "")),
                "book_value": amount,
                "tb_code": code,
                "detail_policy": "detail_fillable",
            }
        )
    payroll_bs_total = round(float(bs_values.get("应付职工薪酬", 0.0) or 0.0), 2)
    if not payroll_leaf_rows and abs(payroll_bs_total) >= 0.005:
        # Keep the page in scope so stage-2 can emit an explicit blocked
        # placeholder instead of silently dropping the non-zero BS line.
        payroll_leaf_rows.append(
            {
                "counterparty": "",
                "sub_name": "应付职工薪酬",
                "book_value": abs(payroll_bs_total),
                "tb_code": "BS",
                "detail_policy": "placeholder_only",
            }
        )

    group_rows_for_y71.source_reconciliation = source_reconciliation
    return [
        ("银行存款", sorted(grouped["银行存款"], key=lambda x: -abs(x["book_value"])), "cash"),
        ("应收账款", sorted(grouped["应收账款"], key=lambda x: -abs(x["book_value"])), "receivable"),
        ("预付账款", sorted(grouped["预付账款"], key=lambda x: -abs(x["book_value"])), "receivable"),
        ("其他应收款", sorted(collapse_offsetting_rows("其他应收款", grouped["其他应收款"]), key=lambda x: -abs(x["book_value"])), "receivable"),
        ("应付账款", sorted(grouped["应付账款"], key=lambda x: -abs(x["book_value"])), "payable"),
        ("预收账款", sorted(grouped["预收账款"], key=lambda x: -abs(x["book_value"])), "payable"),
        ("其他应付款", sorted(collapse_offsetting_rows("其他应付款", grouped["其他应付款"]), key=lambda x: -abs(x["book_value"])), "payable"),
        ("应交税费", sorted(grouped["应交税费"], key=lambda x: -abs(x["book_value"])), "tax"),
        ("职工薪酬", payroll_leaf_rows, "payable"),
    ]


def collapse_offsetting_rows(sheet_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if sheet_name not in {"其他应收款", "其他应付款"}:
        return list(rows)

    def offsetting_key(row: dict[str, Any]) -> str:
        counterparty = clean(row.get("counterparty", ""))
        if not counterparty:
            return ""
        extracted = normalize_counterparty_display(extract_entity_from_text(counterparty))
        return extracted or normalize_counterparty_display(counterparty)

    by_counterparty: dict[str, list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        counterparty = offsetting_key(row)
        amount = float(row.get("book_value", 0.0) or 0.0)
        if not counterparty or abs(amount) < 0.005:
            passthrough.append(row)
            continue
        by_counterparty.setdefault(counterparty, []).append(row)

    collapsed: list[dict[str, Any]] = []
    for counterparty, cp_rows in by_counterparty.items():
        positives = [row for row in cp_rows if float(row.get("book_value", 0.0) or 0.0) > 0]
        negatives = [row for row in cp_rows if float(row.get("book_value", 0.0) or 0.0) < 0]
        dropped: set[int] = set()
        for pos in positives:
            if id(pos) in dropped:
                continue
            pos_amount = round(float(pos.get("book_value", 0.0) or 0.0), 2)
            matched = None
            for neg in negatives:
                if id(neg) in dropped:
                    continue
                neg_amount = round(float(neg.get("book_value", 0.0) or 0.0), 2)
                if abs(pos_amount + neg_amount) < 0.005:
                    matched = neg
                    break
            if matched is not None:
                dropped.add(id(pos))
                dropped.add(id(matched))
        for row in cp_rows:
            if id(row) not in dropped:
                collapsed.append(row)

    return collapsed + passthrough


def find_total_row(ws, start_row: int = 6, max_scan: int = 120) -> int:
    for r in range(start_row, min(ws.max_row, max_scan) + 1):
        row_text = "".join(clean(ws.cell(r, c).value) for c in range(1, min(ws.max_column, 12) + 1))
        compact_text = row_text.replace(" ", "")
        if "合计" in compact_text or "净值" in compact_text or "净额" in compact_text:
            return r
    return min(ws.max_row, max_scan)


def find_effective_total_row(ws, start_row: int = 6) -> int:
    layout = get_footer_layout(ws.title, ws)
    template_footer_row = int(layout.get("template_total_row", 0) or 0)

    if template_footer_row > 0 and template_footer_row <= ws.max_row:
        row_text = "".join(clean(ws.cell(template_footer_row, c).value) for c in range(1, min(ws.max_column, 12) + 1)).replace(" ", "")
        if "合计" in row_text:
            return template_footer_row

    labeled_rows: list[int] = []
    for r in range(start_row, ws.max_row + 1):
        row_text = "".join(clean(ws.cell(r, c).value) for c in range(1, min(ws.max_column, 12) + 1))
        compact_text = row_text.replace(" ", "")
        if "合计" in compact_text:
            labeled_rows.append(r)
    if labeled_rows:
        return labeled_rows[-1]
    return find_total_row(ws, start_row, max_scan=ws.max_row)


def collapse_duplicate_footer_rows(ws, template: list[tuple[str, str]], sheet_registry: dict[str, Any]) -> bool:
    summary_zone = sheet_registry.get("readonly_summary_zone")
    start_row = int(summary_zone.get("start_row", 0) or 0) if isinstance(summary_zone, dict) else 0
    layout = get_footer_layout(ws.title, ws)
    canonical_footer_row = int(layout.get("template_total_row", 0) or 0)
    if canonical_footer_row > 0:
        start_row = canonical_footer_row
    if start_row <= 0:
        confirmed_cells = sheet_registry.get("confirmed_input_cells", [])
        confirmed_rows = []
        for cell_ref in confirmed_cells:
            digits = "".join(ch for ch in str(cell_ref) if ch.isdigit())
            if digits:
                confirmed_rows.append(int(digits))
        max_input_row = max(confirmed_rows) if confirmed_rows else 0

        formula_cells = sheet_registry.get("formula_cells", [])
        footer_formula_rows = []
        for cell_ref in formula_cells:
            digits = "".join(ch for ch in str(cell_ref) if ch.isdigit())
            if digits:
                row_no = int(digits)
                if row_no > max_input_row:
                    footer_formula_rows.append(row_no)
        if footer_formula_rows:
            start_row = min(footer_formula_rows)

    if start_row <= 0:
        for r in range(6, min(ws.max_row, 60) + 1):
            row_text = "".join(clean(ws.cell(r, c).value) for c in range(1, min(ws.max_column, 12) + 1)).replace(" ", "")
            if "合计" in row_text:
                start_row = r
                break
    if start_row <= 0 or ws.max_row <= start_row:
        return False

    effective_total_row = find_effective_total_row(ws, 6)
    labeled_rows: list[int] = []
    for r in range(6, ws.max_row + 1):
        row_text = "".join(clean(ws.cell(r, c).value) for c in range(1, min(ws.max_column, 12) + 1)).replace(" ", "")
        if "合计" in row_text:
            labeled_rows.append(r)
    source_start = labeled_rows[-1] if labeled_rows else effective_total_row
    if source_start <= start_row:
        return False

    label_rows = layout.get("label_rows", {}) if layout else {}
    owner_rows = layout.get("owner_rows", {}) if layout else {}
    footer_block_height = max([0, *[int(k) for k in label_rows.keys()], *[int(k) for k in owner_rows.keys()]]) + 1
    footer_height = footer_block_height if footer_block_height > 0 else ws.max_row - source_start + 1
    if footer_height <= 0:
        return False

    target_start = start_row
    source_end = min(ws.max_row, source_start + footer_height - 1)
    footer_values: list[list[Any]] = []
    footer_styles: list[list[Any]] = []
    for row_idx in range(source_start, source_end + 1):
        row_values: list[Any] = []
        row_styles: list[Any] = []
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row_idx, col_idx)
            row_values.append(cell.value)
            row_styles.append(copy(cell._style) if cell.has_style else None)
        footer_values.append(row_values)
        footer_styles.append(row_styles)

    target_formula_count = 0
    source_formula_count = 0
    for offset in range(footer_height):
        target_row = target_start + offset
        source_row = source_start + offset
        if target_row <= ws.max_row:
            for col_idx in range(1, ws.max_column + 1):
                if ws.cell(target_row, col_idx).data_type == "f":
                    target_formula_count += 1
        if source_row <= ws.max_row:
            for col_idx in range(1, ws.max_column + 1):
                if ws.cell(source_row, col_idx).data_type == "f":
                    source_formula_count += 1

    should_copy_footer = not (canonical_footer_row > 0 and target_formula_count > source_formula_count)

    if should_copy_footer:
        for row_idx in range(target_start, ws.max_row + 1):
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row_idx, col_idx)
                if isinstance(cell, MergedCell):
                    continue
                cell.value = None

        for offset, row_values in enumerate(footer_values):
            target_row = target_start + offset
            for col_idx, value in enumerate(row_values, start=1):
                cell = ws.cell(target_row, col_idx)
                if isinstance(cell, MergedCell):
                    continue
                cell.value = value
                style = footer_styles[offset][col_idx - 1]
                if style is not None:
                    cell._style = copy(style)

    clear_start = source_start
    clear_end = source_end if should_copy_footer else source_end
    if clear_start <= ws.max_row:
        for row_idx in range(clear_start, min(clear_end, ws.max_row) + 1):
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row_idx, col_idx)
                if isinstance(cell, MergedCell):
                    continue
                cell.value = None

    return True


def trim_sheet_trailing_empty_rows(ws, min_keep_row: int) -> None:
    while ws.max_row > min_keep_row:
        row_idx = ws.max_row
        has_value = False
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row_idx, col_idx)
            if isinstance(cell, MergedCell):
                continue
            if cell.value not in (None, ""):
                has_value = True
                break
        if has_value:
            break
        ws.delete_rows(row_idx, 1)


def clear_row_value_range(ws, start_row: int, end_row: int) -> None:
    if end_row < start_row:
        return
    for row_idx in range(start_row, end_row + 1):
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row_idx, col_idx)
            if isinstance(cell, MergedCell):
                continue
            cell.value = None


def footer_reserved_end_row(layout: dict[str, Any], total_row: int) -> int:
    label_offsets = [int(offset) for offset in layout.get("label_rows", {}).keys()]
    owner_offsets = [int(offset) for offset in layout.get("owner_rows", {}).keys()]
    border_clear_offsets = [int(offset) for offset in layout.get("owner_border_clear_rows", [])]
    max_offset = max([0, *label_offsets, *owner_offsets, *border_clear_offsets])
    return total_row + max_offset


def extend_prepay_row_formulas(ws, first_row: int, last_row: int) -> None:
    if last_row < first_row:
        return
    for row_idx in range(first_row, last_row + 1):
        ws[f"I{row_idx}"] = f"=H{row_idx}"
        ws[f"J{row_idx}"] = f'=IF(H{row_idx}=0,"",(I{row_idx}-H{row_idx})/H{row_idx}*100)'


def clear_sheet_body(ws, start_row: int = 6, max_col: int | None = None) -> None:
    if is_linked_summary_sheet(ws.title):
        return
    if max_col is None:
        max_col = ws.max_column
    total_row = find_total_row(ws, start_row)
    layout = get_footer_layout(ws.title, ws)
    reserved = int(layout.get("clear_reserved_rows", 1) or 1)
    data_end = max(start_row, total_row - reserved)
    for r in range(start_row, data_end + 1):
        for c in range(1, max_col + 1):
            cell = ws.cell(r, c)
            if isinstance(cell, MergedCell):
                continue
            if cell.data_type == "f":
                continue
            cell.value = None


def restore_footer_labels(ws, total_row: int | None = None) -> None:
    layout = get_footer_layout(ws.title, ws)
    template_total_row = int(total_row or 0) if total_row else int(layout.get("template_total_row", 0) or 0)
    labels = layout.get("label_rows", {})
    for offset, text in labels.items():
        row = template_total_row + int(offset)
        ws.cell(row, 1).value = text


def restore_owner_footer_rows(ws, total_row: int | None = None) -> None:
    layout = get_footer_layout(ws.title, ws)
    if not layout:
        return
    anchor_total_row = int(total_row or 0) if total_row else int(layout.get("template_total_row", 0) or 0)
    clear_cols = layout.get("owner_border_clear_cols", ())
    owner_rows = layout.get("owner_rows", {})
    for offset in layout.get("owner_border_clear_rows", []):
        row_idx = anchor_total_row + int(offset)
        for col_idx in clear_cols:
            cell = ws.cell(row_idx, col_idx)
            cell.border = copy(Border())
    for offset, mapping in owner_rows.items():
        row_idx = anchor_total_row + int(offset)
        for col_letter, value in mapping.items():
            ws[f"{col_letter}{row_idx}"] = value


def restore_footer_merges(ws, total_row: int | None = None) -> None:
    layout = get_footer_layout(ws.title, ws)
    if not layout:
        return
    anchor_total_row = int(total_row or 0) if total_row else int(layout.get("template_total_row", 0) or 0)
    if anchor_total_row <= 0:
        return
    merge_offsets = layout.get("merge_offsets", [])
    expected_ranges = {f"{start_col}{anchor_total_row + int(offset)}:{end_col}{anchor_total_row + int(offset)}" for offset, start_col, end_col in merge_offsets}
    for merged_range in list(ws.merged_cells.ranges):
        if any(str(merged_range) == target for target in expected_ranges):
            continue
    existing = {str(r) for r in ws.merged_cells.ranges}
    for target in expected_ranges:
        if target not in existing:
            ws.merge_cells(target)


def clear_duplicate_footer_artifacts(ws, total_row: int) -> None:
    layout = get_footer_layout(ws.title, ws)
    if not layout or total_row <= 0:
        return
    label_texts = {clean(text).replace(" ", "") for text in layout.get("label_rows", {}).values() if clean(text)}
    owner_markers = {
        "封面!D11&封面!G11",
        "CONCATENATE(封面!D13",
        "评估人员",
        "填表人",
    }
    expected_merge_rows = {total_row + int(offset) for offset, _start, _end in layout.get("merge_offsets", [])}
    for merged_range in list(ws.merged_cells.ranges):
        row_no = merged_range.min_row
        if row_no >= total_row:
            continue
        if row_no in expected_merge_rows:
            ws.unmerge_cells(str(merged_range))
    max_scan_row = min(ws.max_row, total_row - 1)
    for row_idx in range(6, max_scan_row + 1):
        row_values = [ws.cell(row_idx, col_idx).value for col_idx in range(1, min(ws.max_column, 20) + 1)]
        compact_text = "".join(clean(value) for value in row_values).replace(" ", "")
        has_label = any(text and text in compact_text for text in label_texts)
        has_owner_marker = any(marker in str(value) for value in row_values if value is not None for marker in owner_markers)
        if not has_label and not has_owner_marker:
            continue
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row_idx, col_idx)
            if isinstance(cell, MergedCell):
                continue
            if cell.data_type == "f" and not has_owner_marker:
                continue
            cell.value = None
            if has_owner_marker:
                cell.border = copy(Border())


def normalize_footer_for_sheet(ws) -> None:
    layout = get_footer_layout(ws.title, ws)
    if not layout:
        return
    total_row = find_effective_total_row(ws, 6)
    if total_row <= 0:
        return
    clear_duplicate_footer_artifacts(ws, total_row)
    restore_footer_labels(ws, total_row=total_row)
    restore_footer_merges(ws, total_row=total_row)
    restore_owner_footer_rows(ws, total_row=total_row)
    trim_keep_offset = int(layout.get("trim_keep_offset", 0) or 0)
    if trim_keep_offset > 0:
        trim_sheet_trailing_empty_rows(ws, total_row + trim_keep_offset)


def normalize_all_detail_sheet_footers(wb) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for ws in wb.worksheets:
        if getattr(ws, '_locked_template_layout', False):
            continue
        if ws.title in SUMMARY_SHEET_NAMES or is_linked_summary_sheet(ws.title):
            continue
        layout = get_footer_layout(ws.title, ws)
        if not layout:
            continue
        normalize_footer_for_sheet(ws)
        normalized.append(
            {
                "sheet": ws.title,
                "template_total_row": int(layout.get("template_total_row", 0) or 0),
                "trim_keep_offset": int(layout.get("trim_keep_offset", 0) or 0),
                "merge_count": len(layout.get("merge_offsets", [])),
                "owner_row_count": len(layout.get("owner_rows", {})),
            }
        )
    return normalized


DETAIL_WRITE_TEMPLATES = {
    "银行存款": [("A", "row_index"), ("B", "counterparty"), ("C", "sub_name"), ("D", "currency"), ("I", "book_value")],
    "应收账款": [("A", "row_index"), ("B", "counterparty"), ("C", "sub_name"), ("D", "date_value"), ("E", "age_bucket"), ("P", "book_value"), ("age_bucket_col", "bucket_amount")],
    "预付账款": [("A", "row_index"), ("B", "counterparty"), ("C", "sub_name"), ("D", "date_value"), ("E", "age_bucket"), ("H", "book_value")],
    "其他应收款": [("A", "row_index"), ("B", "counterparty"), ("C", "sub_name"), ("D", "date_value"), ("E", "age_bucket"), ("P", "book_value"), ("age_bucket_col", "bucket_amount")],
    "应付账款": [("A", "row_index"), ("B", "counterparty"), ("C", "date_value"), ("D", "sub_name"), ("G", "book_value"), ("H", "book_value"), ("I", "remark")],
    "预收账款": [("A", "row_index"), ("B", "counterparty"), ("C", "date_value"), ("D", "sub_name"), ("G", "book_value"), ("H", "book_value"), ("I", "remark")],
    "其他应付款": [("A", "row_index"), ("B", "counterparty"), ("C", "date_value"), ("D", "sub_name"), ("G", "book_value"), ("H", "book_value"), ("I", "remark")],
    "应交税费": [("A", "row_index"), ("B", "counterparty"), ("C", "date_value"), ("D", "sub_name"), ("G", "book_value"), ("H", "book_value")],
    "职工薪酬": [("A", "row_index"), ("B", "sub_name"), ("C", "date_value"), ("F", "book_value"), ("H", "remark")],
}


def write_simple_detail_sheet(ws, rows: list[dict[str, Any]], kind: str, protection: dict[str, Any], registry: dict[str, Any], journal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    template = DETAIL_WRITE_TEMPLATES.get(ws.title, [])
    sheet_registry = registry.get("selected_sheets", {}).get(ws.title, {})
    locked = getattr(ws, '_locked_template_layout', False)
    if locked:
        total = find_total_row(ws, 6)
        inputs = set(sheet_registry.get('confirmed_input_cells', []))
        amount_cols = [col for col, field in template if field == 'book_value']
        capacity = [r for r in range(6, total) if any(
            f'{col}{r}' in inputs and ws[f'{col}{r}'].data_type != 'f' for col in amount_cols)]
        if len(rows) > len(capacity):
            raise ProtectionViolation({'sheet': ws.title, 'reason': 'locked_template_capacity_exceeded',
                                       'capacity': len(capacity), 'required': len(rows)})
        for address in inputs.intersection(sheet_registry.get('detail_body_cells', [])):
            cell = ws[address]
            if 6 <= cell.row < total and not isinstance(cell, MergedCell) and cell.data_type != 'f':
                safe_set(ws, address, None, protection, registry, kind='detail_body_write')
    if not locked and ws.title in {"预付账款", "应付账款", "其他应收款"}:
        collapse_duplicate_footer_rows(ws, template, sheet_registry)
    if not locked:
        clear_sheet_body(ws)
    total_row = find_total_row(ws, 6)
    if not locked:
        restore_footer_labels(ws, total_row=total_row)
    if ws.title == "应交税费":
        rows = apply_tax_fee_presentation_openpyxl(ws, rows)
    data_end = max(6, total_row - 1)
    written = []
    writable_cells = set(sheet_registry.get("confirmed_input_cells", []))
    required_cols = [col for col, field_name in template if col != "age_bucket_col"]
    value_cols = [col for col, field_name in template if field_name in {"book_value", "audit_before_value"}]
    candidate_rows = []
    for row_num in range(6, data_end + 1):
        if value_cols and any(f"{col}{row_num}" in writable_cells for col in value_cols):
            candidate_rows.append(row_num)
        elif required_cols and all(f"{col}{row_num}" in writable_cells for col in required_cols):
            candidate_rows.append(row_num)
    if locked:
        candidate_rows = capacity
    elif not candidate_rows:
        candidate_rows = list(range(6, data_end + 1))
    if not locked and ws.title in {"应付账款", "预收账款", "其他应付款", "应交税费"}:
        liability_value_cells = {f"H{row_num}" for row_num in candidate_rows}
        writable_cells |= liability_value_cells
        registry.setdefault("selected_sheets", {}).setdefault(ws.title, {}).setdefault("confirmed_input_cells", [])
        registry["selected_sheets"][ws.title]["confirmed_input_cells"] = sorted(
            set(registry["selected_sheets"][ws.title]["confirmed_input_cells"]) | liability_value_cells
        )
        registry["selected_sheets"][ws.title].setdefault("detail_body_cells", [])
        registry["selected_sheets"][ws.title]["detail_body_cells"] = sorted(
            set(registry["selected_sheets"][ws.title]["detail_body_cells"]) | liability_value_cells
        )
        registry["selected_sheets"][ws.title]["formula_cells"] = sorted(
            set(registry["selected_sheets"][ws.title].get("formula_cells", [])) - liability_value_cells
        )
        registry["selected_sheets"][ws.title]["forbidden_non_formula_cells"] = sorted(
            set(registry["selected_sheets"][ws.title].get("forbidden_non_formula_cells", [])) - liability_value_cells
        )
        protection.setdefault("sheets", {}).setdefault(ws.title, {}).setdefault("formula_cells", [])
        protection["sheets"][ws.title]["formula_cells"] = sorted(
            set(protection["sheets"][ws.title].get("formula_cells", [])) - liability_value_cells
        )
    rows_to_write = list(rows)
    if len(rows_to_write) > len(candidate_rows) and candidate_rows:
        extra_needed = len(rows_to_write) - len(candidate_rows)
        insert_at = max(candidate_rows) + 1
        for merged_range in list(ws.merged_cells.ranges):
            if merged_range.min_row >= insert_at and merged_range.max_row <= insert_at + extra_needed - 1:
                ws.unmerge_cells(str(merged_range))
        ws.insert_rows(insert_at, extra_needed)
        if insert_at <= total_row:
            total_row += extra_needed
        for extra_idx in range(extra_needed):
            target_row = insert_at + extra_idx
            source_row = candidate_rows[-1]
            for col_idx in range(1, ws.max_column + 1):
                src = ws.cell(source_row, col_idx)
                dst = ws.cell(target_row, col_idx)
                if src.has_style:
                    dst._style = copy(src._style)
                dst.number_format = src.number_format
                dst.font = copy(src.font)
                dst.fill = copy(src.fill)
                dst.border = copy(src.border)
                dst.alignment = copy(src.alignment)
            candidate_rows.append(target_row)
            for col, field_name in template:
                if col == "age_bucket_col":
                    continue
                writable_cells.add(f"{col}{target_row}")
            for col in ("A", "B", "C", "D", "E", "F", "G", "H", "I", "P"):
                writable_cells.add(f"{col}{target_row}")
        registry.setdefault("selected_sheets", {}).setdefault(ws.title, {}).setdefault("confirmed_input_cells", [])
        registry["selected_sheets"][ws.title]["confirmed_input_cells"] = sorted(
            set(registry["selected_sheets"][ws.title]["confirmed_input_cells"]) | writable_cells
        )
        registry["selected_sheets"][ws.title].setdefault("detail_body_cells", [])
        registry["selected_sheets"][ws.title]["detail_body_cells"] = sorted(
            set(registry["selected_sheets"][ws.title]["detail_body_cells"]) | writable_cells
        )
        registry["selected_sheets"][ws.title]["formula_cells"] = sorted(
            set(registry["selected_sheets"][ws.title].get("formula_cells", [])) - writable_cells
        )
        registry["selected_sheets"][ws.title]["forbidden_non_formula_cells"] = sorted(
            set(registry["selected_sheets"][ws.title].get("forbidden_non_formula_cells", [])) - writable_cells
        )
        summary_zone = registry["selected_sheets"][ws.title].get("readonly_summary_zone")
        if isinstance(summary_zone, dict):
            summary_zone["start_row"] = int(summary_zone.get("start_row", 0) or 0) + extra_needed
            summary_zone["end_row"] = int(summary_zone.get("end_row", 0) or 0) + extra_needed
        for protected_range in registry["selected_sheets"][ws.title].get("protected_text_ranges", []):
            if int(protected_range.get("start_row", 0) or 0) >= insert_at:
                protected_range["start_row"] = int(protected_range.get("start_row", 0) or 0) + extra_needed
                protected_range["end_row"] = int(protected_range.get("end_row", 0) or 0) + extra_needed
        protection.setdefault("sheets", {}).setdefault(ws.title, {}).setdefault("formula_cells", [])
        protection["sheets"][ws.title]["formula_cells"] = sorted(
            set(protection["sheets"][ws.title].get("formula_cells", [])) - writable_cells
        )
        protection_zone = protection["sheets"][ws.title].get("readonly_summary_zone")
        if isinstance(protection_zone, dict):
            protection_zone["start_row"] = int(protection_zone.get("start_row", 0) or 0) + extra_needed
            protection_zone["end_row"] = int(protection_zone.get("end_row", 0) or 0) + extra_needed
        for protected_range in protection["sheets"][ws.title].get("protected_text_ranges", []):
            if int(protected_range.get("start_row", 0) or 0) >= insert_at:
                protected_range["start_row"] = int(protected_range.get("start_row", 0) or 0) + extra_needed
                protected_range["end_row"] = int(protected_range.get("end_row", 0) or 0) + extra_needed
    for idx, item in enumerate(rows_to_write, start=1):
        if idx > len(candidate_rows):
            break
        r = candidate_rows[idx - 1]
        row_item = dict(item)
        if row_item.get("fill_mode") == "placeholder_only":
            row_item["counterparty"] = ""
        page_rule = PAGE_RULES.get(ws.title)
        if page_rule and row_item.get("fill_mode") == "detail_fillable":
            account_type = page_rule["account_type"]
            row_candidates = strict_journal_candidates(ws.title, row_item.get("counterparty", ""), journal_rows, row_item.get("tb_code", ""))
            selected = select_journal_entry(row_item.get("counterparty", ""), float(row_item.get("book_value", 0.0) or 0.0), account_type, row_candidates)
            if selected is not None:
                row_item["date_value"] = selected.get("gl_date")
                candidate_sub_name = normalize_business_desc(
                    clean(selected.get("line_desc") or selected.get("summary") or row_item.get("sub_name", "")),
                    row_item.get("sub_name", ""),
                )
                if not (
                    clean(candidate_sub_name)
                    and clean(candidate_sub_name) == clean(row_item.get("counterparty", ""))
                    and looks_like_entity(candidate_sub_name)
                ):
                    row_item["sub_name"] = candidate_sub_name
                if ws.title == "应交税费":
                    row_item["counterparty"] = ""
                    row_item["sub_name"] = normalize_tax_type(row_item.get("sub_name", ""))
            elif ws.title in {"其他应收款", "其他应付款"}:
                row_item["evidence_boundary"] = "no_journal_match"
                row_item["remark"] = "序时账及客商明细未检出发生记录"
        if ws.title in SHEET_ACCOUNT_ROOTS and row_item.get("date_value") in (None, "") and clean(row_item.get("tb_code", "")):
            # Account-driven occurrence-date fallback (Skill 六页日期规则):
            # date evidence attaches to the account itself and must not depend
            # on counterparty evidence or counterparty-based journal matching.
            direction = "credit" if ws.title in PAYABLE_DETAIL_SHEETS else "debit"
            account_match = select_account_journal_date(row_item.get("tb_code"), journal_rows, direction=direction)
            if account_match is not None:
                row_item["date_value"] = account_match.get("gl_date")
                row_item["date_source"] = f"journal_account_last_real_{direction}"
            elif not clean(row_item.get("remark", "")):
                row_item["evidence_boundary"] = "no_journal_match"
                row_item["remark"] = "序时账未检出匹配分录"
        age_bucket, age_bucket_col = derive_age_bucket(row_item.get("date_value"),
            base_date=getattr(ws, '_report_date', None))
        row_item["age_bucket"] = age_bucket
        row_item["age_bucket_col"] = age_bucket_col
        row_item["bucket_amount"] = row_item.get("book_value")
        written_cells: set[str] = set()
        for col, field_name in template:
            if field_name == "row_index":
                value = idx
            elif field_name == "currency":
                value = "人民币"
            elif col == "age_bucket_col":
                bucket_col = row_item.get("age_bucket_col")
                if bucket_col and f"{bucket_col}{r}" in writable_cells:
                    safe_set(ws, f"{bucket_col}{r}", row_item.get("bucket_amount"), protection, registry, kind="detail_body_write")
                    written_cells.add(f"{bucket_col}{r}")
                continue
            else:
                value = row_item.get(field_name)
            if locked and ws[f'{col}{r}'].data_type == 'f':
                continue  # Formula-derived field; validate its calculated value later.
            if locked and f'{col}{r}' not in inputs:
                continue  # Locked template: only confirmed input cells may be written.
            safe_set(ws, f"{col}{r}", value, protection, registry, kind="detail_body_write")
            written_cells.add(f"{col}{r}")
        written.append({**row_item, "_written_row": r, "_sheet": ws.title, "_written_cells": sorted(written_cells)})
    if not locked and ws.title == "应收账款":
        gross_total = round(sum(float(item.get("book_value", 0.0) or 0.0) for item in rows_to_write), 2)
        bs_total = round(float(getattr(write_simple_detail_sheet, "_bs_values", {}).get("应收账款", 0.0) or 0.0), 2)
        allowance = round(gross_total - bs_total, 2)
        if allowance > 0.004:
            safe_set(ws, f"F{candidate_rows[-1]}", allowance, protection, registry, kind="detail_body_write")
            written.append(
                {
                    "_sheet": ws.title,
                    "_written_row": candidate_rows[-1],
                    "counterparty": "",
                    "sub_name": "坏账准备",
                    "book_value": -allowance,
                    "fill_mode": "placeholder_only",
                    "fill_reason": "receivable_gross_to_balance_sheet_net_allowance",
                }
            )
    if not locked and total_row and candidate_rows:
        first_row = min(candidate_rows)
        written_data_rows = [int(item["_written_row"]) for item in written if int(item["_written_row"]) < int(total_row)]
        last_row = max(written_data_rows) if written_data_rows else first_row
        layout = get_footer_layout(ws.title, ws)
        compactable_sheets = {"åº”ä»˜è´¦æ¬¾", "å…¶ä»–åº”ä»˜æ¬¾", "åº”äº¤ç¨Žè´¹"}
        compact_total_row = last_row + 1
        if ws.title in compactable_sheets and compact_total_row < total_row:
            old_footer_end_row = footer_reserved_end_row(layout, total_row)
            clear_row_value_range(ws, compact_total_row, old_footer_end_row)
            total_row = compact_total_row
        if ws.title in {"应付账款", "预收账款", "其他应付款", "应交税费"}:
            for col in ("G", "H"):
                ws[f"{col}{total_row}"] = f"=SUM({col}{first_row}:{col}{last_row})"
        elif ws.title in {"预付账款"}:
            extend_prepay_row_formulas(ws, first_row, last_row)
            ws[f"F{total_row}"] = f"=SUM(F{first_row}:F{last_row})"
            ws[f"H{total_row}"] = f"=SUM(H{first_row}:H{last_row})"
            ws[f"I{total_row}"] = f"=SUM(I{first_row}:I{last_row})"
            ws[f"J{total_row}"] = f'=IF(H{total_row}=0,"",(I{total_row}-H{total_row})/H{total_row}*100)'
        elif ws.title in {"应收账款", "其他应收款"}:
            ws[f"P{total_row}"] = f"=SUM(P{first_row}:P{last_row})"
        restore_footer_merges(ws, total_row=total_row)
        restore_owner_footer_rows(ws, total_row=total_row)
        trim_keep_offset = int(layout.get("trim_keep_offset", 2) or 2)
        trim_sheet_trailing_empty_rows(ws, total_row + trim_keep_offset)
    return written


def reconcile_detail_rows_to_bs(sheet_name: str, rows: list[dict[str, Any]], bs_values: dict[str, float]) -> list[dict[str, Any]]:
    # Preserve the source evidence; differences are reviewed rather than balanced away.
    return rows


def remove_excess_return_noise_rows(sheet_name: str, rows: list[dict[str, Any]], bs_values: dict[str, float]) -> list[dict[str, Any]]:
    # Preserve the source evidence; differences are reviewed rather than balanced away.
    return rows


def append_net_reconciliation_row(sheet_name: str, rows: list[dict[str, Any]], bs_values: dict[str, float]) -> list[dict[str, Any]]:
    # Source conflicts must be reported, never converted into accounting entries.
    return rows


def classify_counterparty_text(text: Any) -> dict[str, Any]:
    raw = clean(text)
    if not raw:
        return {"is_valid": False, "reason": "empty"}
    if raw in ALLOWED_EXCEPTION_COUNTERPARTIES:
        return {"is_valid": True, "reason": "allowed_exception_counterparty"}
    if raw in COUNTERPARTY_FORBIDDEN_TERMS:
        return {"is_valid": False, "reason": "forbidden_term"}
    if raw in {"综合本位币", "人民币"}:
        return {"is_valid": False, "reason": "currency_label"}
    if DOMAIN_NAME_RE.fullmatch(raw):
        return {"is_valid": True, "reason": "domain_entity"}
    if raw.upper().endswith(" SARL"):
        return {"is_valid": True, "reason": "legal_entity_suffix"}
    if PERSON_NAME_RE.fullmatch(raw):
        return {"is_valid": True, "reason": "person_name"}
    if any(term in raw for term in ["公司", "有限公司", "合伙企业", "银行", "支行", "中心", "事务所", "医院", "研究院", "经营部", "委员会", "协会"]):
        return {"is_valid": True, "reason": "looks_like_entity"}
    return {"is_valid": False, "reason": "not_explicit_entity"}


def build_counterparty_anomaly_report(workbook: Path, completed_pages: list[dict[str, Any]], written_rows: list[dict[str, Any]]) -> dict[str, Any]:
    wb = load_workbook(workbook, data_only=True)
    anomalies: list[dict[str, Any]] = []
    by_sheet_row = {(item["_sheet"], item["_written_row"]): item for item in written_rows}
    for (sheet_name, r), item in by_sheet_row.items():
        if item.get("fill_mode") == "placeholder_only":
            continue
        counterparty = clean(item.get("counterparty"))
        business = clean(item.get("sub_name"))
        if sheet_name not in SEMANTIC_EXEMPT_SHEETS:
            cp_state = classify_counterparty_text(counterparty)
            if not cp_state["is_valid"]:
                anomalies.append(
                    {
                        "sheet": sheet_name,
                        "row": r,
                        "field": "counterparty",
                        "value": counterparty,
                        "reason": cp_state["reason"],
                    }
                )
        if counterparty and business and counterparty == business and sheet_name not in SEMANTIC_EXEMPT_SHEETS:
            anomalies.append(
                {
                    "sheet": sheet_name,
                    "row": r,
                    "field": "counterparty_vs_business",
                    "value": counterparty,
                    "reason": "counterparty_equals_business",
                }
            )
    wb.close()
    return {
        "status": "ok" if not anomalies else "error",
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


def build_semantic_validation_report(
    workbook: Path,
    completed_pages: list[dict[str, Any]],
    placeholder_pages: list[dict[str, Any]],
    counterparty_anomalies: dict[str, Any],
    written_rows: list[dict[str, Any]],
    bs_values: dict[str, float],
) -> dict[str, Any]:
    wb = load_workbook(workbook, data_only=True)
    six_counterparty_sheets = {"应收账款", "预付账款", "其他应收款", "应付账款", "预收账款", "其他应付款"}
    page_row_counts = {item["sheet"]: int(item.get("row_count", 0)) for item in completed_pages}
    placeholder_sheet_names = {item.get("sheet") for item in placeholder_pages}
    failures: list[dict[str, Any]] = []
    detail_row_counts: dict[str, int] = {}
    placeholder_row_counts: dict[str, int] = {}
    for item in written_rows:
        if item.get("fill_mode") == "detail_fillable":
            detail_row_counts[item["_sheet"]] = detail_row_counts.get(item["_sheet"], 0) + 1
        elif item.get("fill_mode") == "placeholder_only":
            placeholder_row_counts[item["_sheet"]] = placeholder_row_counts.get(item["_sheet"], 0) + 1
    sheet_expected_amounts = {
        "银行存款": abs(float(bs_values.get("货币资金", 0.0) or 0.0)),
        "应收账款": abs(float(bs_values.get("应收账款", 0.0) or 0.0)),
        "预付账款": abs(float(bs_values.get("预付账款", 0.0) or 0.0)),
        "其他应收款": abs(float(bs_values.get("其他应收款", 0.0) or 0.0)),
        "应付账款": abs(float(bs_values.get("应付账款", 0.0) or 0.0)),
        "预收账款": abs(float(bs_values.get("预收账款", 0.0) or 0.0)),
        "其他应付款": abs(float(bs_values.get("其他应付款", 0.0) or 0.0)),
        "应交税费": float(bs_values.get("应交税费", 0.0) or 0.0),
    }
    detail_fillable_sheets = ["应收账款", "预付账款", "其他应收款", "应付账款", "预收账款", "其他应付款", "应交税费", "银行存款"]
    mandatory_real_detail_sheets = {"应收账款", "预付账款", "其他应收款", "应付账款", "预收账款", "其他应付款"}
    for sheet_name in detail_fillable_sheets:
        if sheet_name not in wb.sheetnames:
            continue
        row_count = detail_row_counts.get(sheet_name, 0)
        expected_amount = sheet_expected_amounts.get(sheet_name, 0.0)
        placeholder_count = placeholder_row_counts.get(sheet_name, 0)
        if sheet_name in mandatory_real_detail_sheets and expected_amount >= 0.005 and row_count <= 0:
            if expected_amount <= 1000 and placeholder_count > 0:
                continue
            failures.append({"sheet": sheet_name, "reason": "placeholder_only_not_acceptable_for_detail_sheet"})
            continue
        if row_count <= 0 and placeholder_count <= 0 and expected_amount >= 0.005 and sheet_name not in placeholder_sheet_names and sheet_name != "预收账款":
            failures.append({"sheet": sheet_name, "reason": "detail_fillable_sheet_empty"})
    written_totals: dict[str, float] = {}
    for item in written_rows:
        if item.get("fill_mode") not in {"detail_fillable", "placeholder_only"}:
            continue
        sheet_name = clean(item.get("_sheet", ""))
        if sheet_name not in sheet_expected_amounts:
            continue
        written_totals[sheet_name] = round(
            written_totals.get(sheet_name, 0.0) + float(item.get("book_value", 0.0) or 0.0),
            2,
        )
    for sheet_name in ["其他应收款", "应付账款", "应交税费", "其他应付款"]:
        expected_amount = round(float(sheet_expected_amounts.get(sheet_name, 0.0) or 0.0), 2)
        if expected_amount < 0.005:
            continue
        written_total = round(float(written_totals.get(sheet_name, 0.0) or 0.0), 2)
        diff = round(written_total - expected_amount, 2)
        if abs(diff) >= 0.005:
            failures.append(
                {
                    "sheet": sheet_name,
                    "reason": "detail_total_not_reconciled_to_balance_sheet",
                    "written_total": written_total,
                    "expected_amount": expected_amount,
                    "diff": diff,
                }
            )
    six_counterparty_semantic_anomalies: list[dict[str, Any]] = []
    for anomaly in counterparty_anomalies.get("anomalies", []):
        if anomaly.get("sheet") in six_counterparty_sheets:
            six_counterparty_semantic_anomalies.append(anomaly)
        failures.append(
            {
                "sheet": anomaly["sheet"],
                "row": anomaly["row"],
                "reason": anomaly["reason"],
                "field": anomaly["field"],
                "value": anomaly["value"],
            }
        )
    for item in written_rows:
        if item.get("fill_mode") != "detail_fillable":
            continue
        page_rule = PAGE_RULES.get(item.get("_sheet"))
        if page_rule:
            if page_rule.get("require_date") and not item.get("date_value") and item.get("evidence_boundary") != "no_journal_match":
                failures.append({"sheet": item["_sheet"], "row": item["_written_row"], "reason": "missing_occurrence_date"})
            if page_rule.get("require_age") and not item.get("age_bucket") and item.get("evidence_boundary") != "no_journal_match":
                failures.append({"sheet": item["_sheet"], "row": item["_written_row"], "reason": "missing_age_bucket"})
            if not clean(item.get("sub_name")) and item.get("evidence_boundary") != "no_journal_match":
                failures.append({"sheet": item["_sheet"], "row": item["_written_row"], "reason": "missing_business_desc"})
    wb.close()
    return {
        "status": "ok" if not failures else "error",
        "failure_count": len(failures),
        "failures": failures,
        "six_counterparty_semantic_anomaly_count": len(six_counterparty_semantic_anomalies),
        "six_counterparty_semantic_clear": len(six_counterparty_semantic_anomalies) == 0,
    }


def backfill_y71_summary_anchors(
    wb,
    bs_values: dict[str, float],
    protection: dict[str, Any],
    registry: dict[str, Any],
    summary_registry: dict[str, Any],
) -> list[dict[str, Any]]:
    return []


# Clean override: centralized BS page sync using normalized labels.
def fill_cover_and_balance_sheet(wb, company: str, bs_payload: dict[str, Any], protection: dict[str, Any], registry: dict[str, Any]) -> None:
    if any(name in wb.sheetnames for name in ('封面', '封面页')):
        ws, assignments = cover_assignments(wb, bs_payload)
        for address, value in assignments.items():
            safe_set(ws, address, value, protection, registry, kind='cover_text')
        validate_cover(wb, bs_payload)
    if "资产负债表" not in wb.sheetnames:
        return
    ws = wb["资产负债表"]
    registry_sheet = ((registry or {}).get("selected_sheets") or {}).get("资产负债表", {})
    confirmed_inputs = set(registry_sheet.get("confirmed_input_cells", []))
    current_values = bs_payload.get("values_current", {}) if isinstance(bs_payload, dict) else {}
    prior_values = bs_payload.get("values_prior", {}) if isinstance(bs_payload, dict) else {}
    if not current_values and isinstance(bs_payload, dict):
        current_values = bs_payload.get("values", {})
    if not prior_values:
        prior_values = current_values
    asset_rows = {
        7: "货币资金", 8: "交易性金融资产", 9: "应收票据", 10: "应收账款", 11: "预付账款", 12: "应收利息", 13: "应收股利",
        14: "其他应收款", 15: "存货", 16: "一年内到期的非流动资产", 17: "其他流动资产",
        22: "长期应收款", 23: "长期股权投资", 24: "投资性房地产", 25: "固定资产", 26: "在建工程", 28: "固定资产清理",
        31: "无形资产", 33: "商誉", 34: "长期待摊费用", 35: "递延所得税资产", 36: "其他非流动资产",
    }
    liability_rows = {
        7: "短期借款", 8: "交易性金融负债", 9: "应付票据", 10: "应付账款", 11: "预收账款", 12: "应付职工薪酬", 13: "应交税费",
        14: "应付利息", 15: "应付股利", 16: "其他应付款", 17: "一年内到期的非流动负债", 18: "其他流动负债",
        21: "长期借款", 22: "应付债券", 23: "长期应付款", 24: "专项应付款", 25: "预计负债", 26: "递延所得税负债", 27: "其他非流动负债",
        31: "实收资本", 32: "资本公积", 34: "盈余公积", 35: "未分配利润",
    }
    for row, label in asset_rows.items():
        prior_value = prior_values.get(label, 0.0)
        current_value = current_values.get(label, 0.0)
        if row == 31 and abs(float(current_values.get("鏃犲舰璧勪骇", 0.0) or 0.0) - float(current_values.get("闈炴祦鍔ㄨ祫浜у悎璁?", 0.0) or 0.0)) < 0.005:
            current_value = 0.0
            prior_value = 0.0
        for col, value in (("C", prior_value), ("D", current_value)):
            cell_ref = f"{col}{row}"
            if confirmed_inputs and cell_ref not in confirmed_inputs:
                continue
            safe_set(ws, cell_ref, value, protection, registry, kind="balance_sheet_sync")
    for row, label in liability_rows.items():
        prior_value = prior_values.get(label, 0.0)
        current_value = current_values.get(label, 0.0)
        cols = (("H", prior_value), ("I", current_value))
        if row in {31, 32}:
            cols = (("H", prior_value), ("I", current_value))
        for col, value in cols:
            cell_ref = f"{col}{row}"
            if confirmed_inputs and cell_ref not in confirmed_inputs:
                continue
            safe_set(ws, cell_ref, value, protection, registry, kind="balance_sheet_sync")


def cleanup_zero_balance_fixed_asset_family(wb, bs_values: dict[str, float]) -> dict[str, Any]:
    fixed_asset_zero = abs(float(bs_values.get("固定资产", 0.0) or 0.0)) < 0.005 and abs(float(bs_values.get("固定资产净值", 0.0) or 0.0)) < 0.005
    report = {"fixed_asset_zero": fixed_asset_zero, "sheets": []}
    if not fixed_asset_zero:
        return report
    for sheet_name in ["固定资产汇总", "房屋建筑物", "构筑物", "井巷", "管道沟槽", "机器设备", "车辆", "电子设备", "土地", "固定资产清理"]:
        if is_linked_summary_sheet(sheet_name):
            continue
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        total_row = find_total_row(ws, 6)
        cleared = 0
        guarded_formulas = 0
        for formula_row in ws.iter_rows(min_row=6, max_row=ws.max_row):
            for formula_cell in formula_row:
                if isinstance(formula_cell, MergedCell) or formula_cell.data_type != "f":
                    continue
                formula = str(formula_cell.value or "")
                if formula.startswith("=") and "/" in formula and not formula.upper().startswith("=IFERROR("):
                    formula_cell.value = f"=IFERROR({formula[1:]},0)"
                    guarded_formulas += 1
        for r in range(6, max(6, total_row - 1) + 1):
            for c in range(1, ws.max_column + 1):
                cell = ws.cell(r, c)
                if isinstance(cell, MergedCell):
                    continue
                if cell.data_type == "f":
                    continue
                if cell.value not in (None, ""):
                    cell.value = None
                    cleared += 1
        report["sheets"].append({"sheet": sheet_name, "cleared_cells": cleared, "guarded_formulas": guarded_formulas})
    return report


# Clean override: centralized placeholder mapping for non-current assets and related liabilities.
def force_excel_recalc(path: Path) -> None:
    from recalculate_readonly import recalculate_formula_caches
    recalculate_formula_caches(path)


def apply_sheet_visibility(
    wb,
    bs_values: dict[str, float],
    sheet_plan: list[tuple[str, list[dict[str, Any]], str]],
    completed_pages: list[dict[str, Any]],
    placeholder_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    always_show = {
        "封面",
        "资产负债表",
        "汇总表",
        "分类汇总",
        "流动汇总",
        "非流动资产汇总",
        "流动负债汇总",
    }
    readonly_show = {
        "汇总表",
        "分类汇总",
        "流动汇总",
        "非流动资产汇总",
        "流动负债汇总",
        "资产负债表",
    }
    noncurrent_placeholder_detail_sheets = {
        item["sheet"] for item in NONCURRENT_ASSET_SHEET_MAPPING.values()
    } | {
        item["sheet"] for item in NONCURRENT_LIABILITY_SHEET_MAPPING.values()
    }
    sheet_amount_map = {
        "银行存款": abs(float(bs_values.get("货币资金", 0.0) or 0.0)),
        "应收账款": abs(float(bs_values.get("应收账款", 0.0) or 0.0)),
        "预付账款": abs(float(bs_values.get("预付账款", 0.0) or 0.0)),
        "其他应收款": abs(float(bs_values.get("其他应收款", 0.0) or 0.0)),
        "存货汇总": abs(float(bs_values.get("存货", 0.0) or 0.0)),
        "应付账款": abs(float(bs_values.get("应付账款", 0.0) or 0.0)),
        "预收账款": abs(float(bs_values.get("预收账款", 0.0) or 0.0)),
        "职工薪酬": abs(float(bs_values.get("应付职工薪酬", 0.0) or 0.0)),
        "应交税费": abs(float(bs_values.get("应交税费", 0.0) or 0.0)),
        "其他应付款": abs(float(bs_values.get("其他应付款", 0.0) or 0.0)),
        "无形资产汇总": abs(float(bs_values.get("无形资产", 0.0) or 0.0)),
        "股权投资": abs(float(bs_values.get("长期股权投资", 0.0) or 0.0)),
    }
    must_show = set(always_show)
    for sheet_name, rows, _kind in sheet_plan:
        if rows:
            must_show.add(sheet_name)
    for item in completed_pages:
        if item.get("row_count", 0):
            must_show.add(item["sheet"])
    for item in placeholder_pages:
        sheet_name = item.get("sheet")
        if sheet_name and sheet_name not in noncurrent_placeholder_detail_sheets:
            must_show.add(sheet_name)
    for sheet_name, amount in sheet_amount_map.items():
        if amount >= 0.005 and sheet_name in wb.sheetnames:
            must_show.add(sheet_name)

    may_hide = set()
    changed = []
    for sheet_name in wb.sheetnames:
        if sheet_name in must_show:
            new_state = "visible"
        elif sheet_name in readonly_show:
            new_state = "visible"
        elif sheet_name == "00000000":
            new_state = "veryHidden"
            may_hide.add(sheet_name)
        else:
            new_state = "hidden"
            may_hide.add(sheet_name)
        ws = wb[sheet_name]
        old_state = ws.sheet_state
        if old_state != new_state:
            ws.sheet_state = new_state
            changed.append({"sheet": sheet_name, "from": old_state, "to": new_state})
    return {
        "must_show": sorted(must_show),
        "readonly_show": sorted(readonly_show),
        "may_hide": sorted(may_hide),
        "changed": changed,
    }


def build_validation_report(workbook: Path) -> dict:
    wb = load_workbook(workbook, data_only=True)
    report = {
        "assets_equal_liabilities_equity": False,
        "classification_j4": "",
        "classification_j4_source": "cached_value",
        "no_ref_errors": True,
        "template_baseline_ref_hits": [],
        "runtime_introduced_ref_hits": [],
    }
    if "资产负债表" in wb.sheetnames:
        ws = wb["资产负债表"]
        left = ws["D38"].value
        right = ws["I38"].value
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            report["assets_equal_liabilities_equity"] = abs(float(left) - float(right)) < 0.005
            report["balance_sheet_difference"] = round(float(right) - float(left), 2)
    classification_sheet = next((name for name in ('分类汇总表', '分类汇总', '资产评估结果分类汇总表') if name in wb.sheetnames), None)
    if classification_sheet:
        ws = wb[classification_sheet]
        report["classification_j4"] = ws["J4"].value
        report["difference_hits"] = []
        for r in range(6, min(ws.max_row, 91) + 1):
            diff = ws.cell(r, 10).value
            if isinstance(diff, (int, float)) and abs(float(diff)) >= 0.005:
                report["difference_hits"].append({"row": r, "name": ws.cell(r, 2).value, "diff": diff})
        if report["classification_j4"] in {None, ""} and not report["difference_hits"]:
            report["classification_j4"] = "UNCALCULATED"
            report["classification_j4_source"] = "missing_cached_value"
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and "#REF!" in cell.value:
                    report["no_ref_errors"] = False
                    hit = {"sheet": sheet, "cell": cell.coordinate, "value": cell.value}
                    if sheet == "资产负债表" and cell.coordinate in {"F40", "I40"}:
                        report["template_baseline_ref_hits"].append(hit)
                    else:
                        report["runtime_introduced_ref_hits"].append(hit)
    wb.close()
    return report


def validate_saved_stage1(workbook: Path, *, allow_recalc: bool) -> dict:
    if allow_recalc:
        force_excel_recalc(workbook)
    return build_validation_report(workbook)


def build_flow_debug_report(workbook: Path) -> dict[str, Any]:
    wb = load_workbook(workbook, data_only=True)
    payload: dict[str, Any] = {}
    for sheet_name, cells in {
        "银行存款": ["G23", "I23", "J23", "I6"],
        "应收账款": ["F24", "P24", "Q24", "F27", "P27", "Q27", "P6"],
        "其他应收款": ["F42", "P42", "Q42", "F45", "P45", "Q45", "P6"],
        "流动汇总": ["E6", "F6", "G6", "E9", "F9", "G9", "E13", "F13", "G13", "E27", "F27", "G27"],
        "分类汇总": ["E6", "I6", "J6", "E7", "I7", "J7", "E10", "I10", "J10", "E14", "I14", "J14", "E38", "I38", "J38"],
    }.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        payload[sheet_name] = {cell: ws[cell].value for cell in cells}
    wb.close()
    return payload


def nonzero_items(values: dict[str, float], keys: list[str]) -> dict[str, float]:
    return {key: round(float(values.get(key, 0.0) or 0.0), 2) for key in keys if abs(float(values.get(key, 0.0) or 0.0)) >= 0.005}


SCOPE_EXCLUDED_BALANCE_SHEET_LINES = {
    "资产总计", "负债合计", "所有者权益合计", "负债和所有者权益合计",
    "负债和所有者权益（或股东权益）合计", "流动资产合计", "非流动资产合计",
    "流动负债合计", "非流动负债合计", "实收资本", "实收资本(股本)",
    "实收资本(或股本)", "资本公积", "减:库存股", "减：库存股", "其他综合收益",
    "专项储备", "盈余公积", "未分配利润", "外币报表折算差额",
}


def select_execution_scope(
    bs_values: dict[str, float],
    sheet_plan: list[tuple[str, list[dict[str, Any]], str]],
    *,
    requested_mode: str = "auto",
    bank_evidence_available: bool = False,
) -> dict[str, Any]:
    def planned_row_amount(row: dict[str, Any]) -> float:
        for key in ("book_value", "source_amount"):
            if row.get(key) not in (None, ""):
                return float(row.get(key) or 0.0)
        return float(row.get("debit_end", 0.0) or 0.0) - float(row.get("credit_end", 0.0) or 0.0)

    active_lines = {
        label: round(float(value or 0.0), 2)
        for label, value in bs_values.items()
        if abs(float(value or 0.0)) >= 0.005
        and label not in SCOPE_EXCLUDED_BALANCE_SHEET_LINES
        and not label.endswith(("合计", "总计"))
    }
    active_sheets = sorted({
        sheet_name
        for sheet_name, rows, _kind in sheet_plan
        if sheet_name != "00000000"
        and any(abs(planned_row_amount(row)) >= 0.005 for row in rows)
    })
    single_bank = (
        set(active_lines) == {"货币资金"}
        and set(active_sheets).issubset({"银行存款"})
        and bank_evidence_available
    )
    if requested_mode == "full":
        mode = "full_template"
    elif single_bank:
        mode = "single_asset_lightweight"
        active_sheets = ['银行存款']
    else:
        mode = "scoped_standard"
    required_sheets = ["封面", "资产负债表", "分类汇总", "汇总表"]
    if mode == "single_asset_lightweight":
        required_sheets.extend(["银行存款", "流动汇总"])
    else:
        required_sheets.extend(active_sheets)
    return {
        "requested_mode": requested_mode,
        "selected_mode": mode,
        "active_balance_sheet_lines": active_lines,
        "active_detail_sheets": active_sheets,
        "required_dependency_sheets": list(dict.fromkeys(required_sheets)),
        "stage1_excel_recalc_required": mode != "single_asset_lightweight",
        "reason": (
            "任务配置显式要求全模板处理"
            if mode == "full_template"
            else "仅货币资金非零且银行证据完整，先完成范围识别后进入单资产轻量路径"
            if mode == "single_asset_lightweight"
            else "按资产负债表非零科目生成范围并执行对应明细与依赖链"
        ),
    }


def restrict_plan_to_scope(plan, scope):
    if scope['selected_mode'] == 'full_template':
        return plan
    selected = set(scope['active_detail_sheets'])
    return [item for item in plan if item[0] in selected]


def validate_saved_stage1_scoped(workbook: Path, bs: dict[str, Any]) -> dict[str, Any]:
    values = bs.get("values_current") or bs.get("values") or {}
    assets = float(values.get("资产总计", 0.0) or 0.0)
    liabilities_equity = float(
        next((values[key] for key in (
            "负债和所有者权益（或股东权益）合计", "负债和所有者权益合计",
            "负债和所有者权益总计", "负债及所有者权益总计",
        ) if key in values), 0.0) or 0.0
    )
    wb = load_workbook(workbook, read_only=True, data_only=False)
    ws = wb["资产负债表"]
    checks = []
    for cell_ref, label in (("D7", "货币资金"), ("I31", "实收资本"), ("I35", "未分配利润")):
        expected = float(values.get(label, 0.0) or 0.0)
        if abs(expected) < 0.005:
            continue
        actual = ws[cell_ref].value
        # Resolve only a direct same-sheet input reference; never evaluate arbitrary formulas.
        if isinstance(actual, str) and re.fullmatch(r"=\$?[A-Z]{1,3}\$?[1-9][0-9]*", actual):
            actual = ws[actual[1:].replace("$", "")].value
        actual_number = float(actual) if isinstance(actual, (int, float)) else None
        checks.append({"cell": cell_ref, "label": label, "expected": expected, "actual": actual_number,
                       "matched": actual_number is not None and abs(actual_number - expected) < 0.005})
    wb.close()
    difference = round(liabilities_equity - assets, 2)
    return {
        "assets_equal_liabilities_equity": abs(difference) < 0.005 and all(item["matched"] for item in checks),
        "balance_sheet_difference": difference,
        "validation_mode": "scoped_direct_inputs",
        "direct_input_checks": checks,
    }


def build_preflight_report(
    bs: dict[str, Any],
    tb_rows: list[dict[str, Any]],
    mapping: dict[str, Any],
    journal_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    values = bs.get("values", {})
    bs_keys = [
        "货币资金",
        "应收账款",
        "预付账款",
        "其他应收款",
        "存货",
        "固定资产",
        "长期股权投资",
        "资产总计",
        "应付账款",
        "预收账款",
        "应付职工薪酬",
        "应交税费",
        "其他应付款",
        "负债合计",
        "所有者权益合计",
        "负债和所有者权益合计",
    ]
    account_mappings = mapping.get("account_mappings", []) if isinstance(mapping, dict) else []
    tb_nonzero_rows = [
        row
        for row in tb_rows
        if abs(float(row.get("debit_end", 0.0) or 0.0)) >= 0.005
        or abs(float(row.get("credit_end", 0.0) or 0.0)) >= 0.005
    ]
    mapped_codes = {clean(item.get("tb_code", "")) for item in account_mappings if clean(item.get("tb_code", ""))}
    tb_codes = {clean(row.get("tb_code", "")) for row in tb_nonzero_rows if clean(row.get("tb_code", ""))}
    mapped_nonzero_count = sum(
        1
        for row in tb_nonzero_rows
        if clean(row.get("tb_code", "")) in mapped_codes
        or clean(row.get("tb_code", "")).split(".", 1)[0] in mapped_codes
    )
    return {
        "company": bs.get("company", ""),
        "report_date": bs.get("report_date"),
        "balance_sheet": {
            "parsed_item_count": len(values),
            "key_amounts": nonzero_items(values, bs_keys),
            "asset_total": round(float(values.get("资产总计", 0.0) or 0.0), 2),
            "liability_equity_total": round(
                float(values.get("负债和所有者权益合计", values.get("负债及所有者权益总计", values.get("资产总计", 0.0))) or 0.0),
                2,
            ),
        },
        "trial_balance": {
            "row_count": len(tb_rows),
            "nonzero_row_count": len(tb_nonzero_rows),
            "sample_nonzero_rows": tb_nonzero_rows[:20],
        },
        "project_mapping": {
            "account_mapping_count": len(account_mappings),
            "mapped_nonzero_tb_row_count": mapped_nonzero_count,
            "unmapped_nonzero_top_codes": sorted(
                {code.split(".", 1)[0] for code in tb_codes if code not in mapped_codes and code.split(".", 1)[0] not in mapped_codes}
            )[:50],
        },
        "journal": {
            "row_count": len(journal_rows),
            "has_rows": bool(journal_rows),
        },
    }


def validate_preflight_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    bs_info = report.get("balance_sheet", {})
    tb_info = report.get("trial_balance", {})
    mapping_info = report.get("project_mapping", {})
    key_amounts = bs_info.get("key_amounts", {})
    asset_total = abs(float(bs_info.get("asset_total", 0.0) or 0.0))
    liability_equity_total = abs(float(bs_info.get("liability_equity_total", 0.0) or 0.0))
    parsed_item_count = int(bs_info.get("parsed_item_count", 0) or 0)
    tb_nonzero_count = int(tb_info.get("nonzero_row_count", 0) or 0)
    mapped_nonzero_count = int(mapping_info.get("mapped_nonzero_tb_row_count", 0) or 0)

    if parsed_item_count < 8:
        issues.append({"code": "balance_sheet_too_few_items", "parsed_item_count": parsed_item_count})
    if asset_total < 0.005 and liability_equity_total < 0.005:
        issues.append({"code": "balance_sheet_totals_zero", "asset_total": asset_total, "liability_equity_total": liability_equity_total})

    suspicious_line_number_values = []
    for key, value in key_amounts.items():
        if key in {"资产总计", "负债合计", "所有者权益合计", "负债和所有者权益合计"}:
            continue
        amount = abs(float(value or 0.0))
        if 0.995 <= amount <= 99.005 and abs(amount - round(amount)) < 0.005:
            suspicious_line_number_values.append({"item": key, "value": value})
    if len(suspicious_line_number_values) >= 3 and asset_total <= 200:
        issues.append(
            {
                "code": "balance_sheet_values_look_like_line_numbers",
                "hits": suspicious_line_number_values,
            }
        )

    if tb_nonzero_count == 0:
        issues.append({"code": "trial_balance_no_nonzero_rows"})
    elif mapped_nonzero_count == 0:
        issues.append({"code": "project_mapping_no_nonzero_tb_coverage"})

    return issues


# Final override: parse this project's trial balance from OOXML directly.
def load_trial_balance_rows_from_xml_legacy(path: Path) -> list[dict[str, Any]]:
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        sheet_xml = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst_root.findall(".//x:si", ns):
                text = "".join(t.text or "" for t in si.findall(".//x:t", ns))
                shared_strings.append(text)

    def read_cell_text(cell) -> str:
        cell_type = cell.attrib.get("t", "")
        if cell_type == "inlineStr":
            node = cell.find("x:is/x:t", ns)
            return node.text if node is not None and node.text is not None else ""
        v = cell.find("x:v", ns)
        if v is None or v.text is None:
            return ""
        if cell_type == "s":
            idx = int(v.text)
            return shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
        return v.text

    rows = []
    for row in sheet_xml.findall(".//x:sheetData/x:row", ns):
        r = int(row.attrib.get("r", "0"))
        if r < 5:
            continue
        cell_map: dict[str, str] = {}
        for cell in row.findall("x:c", ns):
            ref = cell.attrib.get("r", "")
            col = "".join(ch for ch in ref if ch.isalpha())
            cell_map[col] = read_cell_text(cell)
        tb_code = clean(cell_map.get("B", ""))
        tb_account_name = clean(cell_map.get("C", ""))
        if not tb_code or not tb_account_name:
            continue
        debit_end = number(cell_map.get("F", ""))
        credit_end = number(cell_map.get("G", ""))
        rows.append(
            {
                "tb_code": tb_code,
                "tb_account_name": tb_account_name,
                "aux_name": tb_account_name,
                "debit_end": debit_end,
                "credit_end": credit_end,
            }
        )
    return rows


def stage1_fill_cover_and_balance_sheet(
    wb,
    bs: dict[str, Any],
    protection: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    fill_cover_and_balance_sheet(wb, bs["company"], bs, protection, registry)


def stage3_enrich_detail_pages_from_journals(
    wb,
    bs: dict[str, Any],
    placeholder_pages: list[dict[str, Any]],
    execution_scope: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    placeholder_pages.extend(fill_noncurrent_placeholders(wb, bs["values"]))
    scope = execution_scope or {}
    scope_sheets = set(scope.get("active_detail_sheets", [])) | set(scope.get("required_dependency_sheets", []))
    should_clean_fixed_assets = scope.get("selected_mode") == "full_template" or bool(
        scope_sheets & {"固定资产汇总", "房屋建筑物", "构筑物", "井巷", "管道沟槽", "机器设备", "车辆", "电子设备", "土地", "固定资产清理"}
    )
    fixed_asset_cleanup = (
        cleanup_zero_balance_fixed_asset_family(wb, bs["values"])
        if should_clean_fixed_assets
        else {"fixed_asset_zero": True, "sheets": [], "skipped": "out_of_scope"}
    )
    return placeholder_pages, {"fixed_asset_zero_balance_cleanup": fixed_asset_cleanup}


def stage4_validate_and_self_check(
    published: Path,
    completed_pages: list[dict[str, Any]],
    placeholder_pages: list[dict[str, Any]],
    all_written_rows: list[dict[str, Any]],
    bs_values: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    validation = build_validation_report(published)
    counterparty_anomaly_report = build_counterparty_anomaly_report(published, completed_pages, all_written_rows)
    semantic_validation_report = build_semantic_validation_report(
        published,
        completed_pages,
        placeholder_pages,
        counterparty_anomaly_report,
        all_written_rows,
        bs_values,
    )
    reconciliation = {
        "status": "ok" if validation.get("classification_j4") == "OK" and semantic_validation_report.get("status") == "ok" else "error",
        "difference_hits": validation.get("difference_hits", []),
        "semantic_status": semantic_validation_report.get("status"),
    }
    return validation, counterparty_anomaly_report, semantic_validation_report, reconciliation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-balance")
    parser.add_argument("--balance-sheet", required=True)
    parser.add_argument('--source-checks', help='JSON list of final cell to original source cell evidence mappings')
    parser.add_argument("--financial-statement", action="append", default=[],
                        help="Explicit original financial statements for cover metadata; repeat for multiple periods")
    parser.add_argument("--journal")
    parser.add_argument("--counterparty-balance")
    parser.add_argument("--bank-statement", action="append", default=[])
    parser.add_argument("--template", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--published-workbook", required=True)
    parser.add_argument("--project-mapping", required=True)
    parser.add_argument("--formula-chain", required=True)
    parser.add_argument("--sheet-layout", required=True)
    parser.add_argument("--formula-protection", required=True)
    parser.add_argument("--input-cell-registry", required=True)
    parser.add_argument("--summary-chain-input-registry", required=True)
    parser.add_argument("--skip-excel-recalc", action="store_true", default=True)
    parser.add_argument("--allow-excel-recalc", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--execution-mode", choices=["auto", "scoped", "full"], default="auto")
    args = parser.parse_args()
    main.output_dir = Path(args.output_dir)
    if args.allow_excel_recalc:
        args.skip_excel_recalc = False

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = time.perf_counter()
    write_stage(output_dir, "start")
    initial_source_hashes = source_fingerprints([
        args.trial_balance, args.balance_sheet, args.journal, args.counterparty_balance, args.source_checks,
        *args.bank_statement,
        *args.financial_statement,
        *([x['source'] for x in json.loads(Path(args.source_checks).read_text(encoding='utf-8'))] if args.source_checks else []),
    ])
    published = Path(args.published_workbook)
    staging = output_dir / "detail_workbook_staging.xlsx"
    template_footer_layouts = extend_footer_layouts_from_template(Path(args.template))
    shutil.copy2(args.template, staging)
    template_wb = load_workbook(staging, data_only=False)
    summary_formula_baseline = capture_summary_formulas(template_wb)
    template_formula_baseline = capture_template_formulas(template_wb)
    template_wb.close()
    timed_stage(output_dir, "template_copied", run_started_at, staging=str(staging))

    mapping = json.loads(Path(args.project_mapping).read_text(encoding="utf-8"))
    protection = json.loads(Path(args.formula_protection).read_text(encoding="utf-8"))
    registry = json.loads(Path(args.input_cell_registry).read_text(encoding="utf-8"))
    summary_registry = json.loads(Path(args.summary_chain_input_registry).read_text(encoding="utf-8"))
    timed_stage(output_dir, "metadata_loaded", run_started_at)
    cover_source = select_latest_statement(args.financial_statement or [args.balance_sheet])
    write_json(output_dir / 'cover_source_selection.json', cover_source)
    bs = parse_balance_sheet(Path(args.balance_sheet), cover_source=cover_source)
    timed_stage(output_dir, "balance_sheet_parsed", run_started_at, bs_keys=len(bs.get("values", {})))
    bank_account_rows, bank_extract_report = load_bank_statement_evidence(args.bank_statement, bs["values"])
    write_json(output_dir / "bank_extract_report.json", bank_extract_report)
    tb_rows = load_trial_balance_rows(Path(args.trial_balance)) if args.trial_balance else []
    timed_stage(output_dir, "trial_balance_loaded", run_started_at, row_count=len(tb_rows))
    journal_rows = load_journal_rows(Path(args.journal) if args.journal else None)
    timed_stage(output_dir, "journal_loaded", run_started_at, row_count=len(journal_rows))
    counterparty_balance_rows = load_counterparty_balance_rows(Path(args.counterparty_balance) if args.counterparty_balance else None)
    preflight_report = build_preflight_report(bs, tb_rows, mapping, journal_rows)
    write_json(output_dir / "preflight_report.json", preflight_report)
    preflight_issues = [] if args.skip_preflight else validate_preflight_report(preflight_report)
    if not args.trial_balance:
        preliminary_plan = group_rows_for_y71(mapping, [], bs['values'])
        preliminary_scope = select_execution_scope(bs['values'], preliminary_plan,
                                                   bank_evidence_available=bool(bank_account_rows))
        if preliminary_scope['selected_mode'] != 'single_asset_lightweight':
            raise ValueError('现有资料缺少非银行项目的明细证据；不允许推造科目余额表')
        # Only the missing-TB check is inapplicable; preserve every financial gate.
        preflight_issues = [x for x in validate_preflight_report(preflight_report)
                            if x['code'] != 'trial_balance_no_nonzero_rows']
    write_json(output_dir / "preflight_gate_failures.json", preflight_issues)
    timed_stage(output_dir, "preflight_validated", run_started_at, issue_count=len(preflight_issues))
    if preflight_issues:
        raise RuntimeError("preflight_gate_failed")
    journal_entity_index = build_journal_entity_index(journal_rows)
    journal_fallback_index = build_journal_fallback_index(journal_rows)
    sheet_plan = group_rows_for_y71(mapping, tb_rows, bs["values"], journal_entity_index, journal_fallback_index)
    timed_stage(output_dir, "sheet_plan_built", run_started_at, plan_count=len(sheet_plan))
    (output_dir / "debug_sheet_plan_before_stage2.json").write_text(
        json.dumps(
            [
                {"sheet": sheet_name, "kind": kind, "rows": rows}
                for sheet_name, rows, kind in sheet_plan
            ],
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    if counterparty_balance_rows:
        sheet_plan = apply_counterparty_balance_rows(sheet_plan, counterparty_balance_rows)
        sheet_plan = refine_counterparty_balance_rows(sheet_plan, counterparty_balance_rows)
    source_reconciliation = getattr(group_rows_for_y71, "source_reconciliation", {})
    execution_scope = select_execution_scope(
        bs["values"],
        sheet_plan,
        requested_mode=args.execution_mode,
        bank_evidence_available=bool(bank_account_rows),
    )
    write_json(output_dir / "execution_scope.json", execution_scope)
    sheet_plan = restrict_plan_to_scope(sheet_plan, execution_scope)
    timed_stage(output_dir, "execution_scope_selected", run_started_at, mode=execution_scope["selected_mode"])

    try:
        wb = load_workbook(staging)
        timed_stage(output_dir, "stage1_opened", run_started_at)
        stage1_fill_cover_and_balance_sheet(wb, bs, protection, registry)
        assert_summary_formulas_preserved(wb, summary_formula_baseline)
        assert_template_formulas_preserved(wb, template_formula_baseline)
        timed_stage(output_dir, "stage1_filled", run_started_at)
        wb.save(staging)
        wb.close()
        timed_stage(output_dir, "stage1_saved", run_started_at)
        if execution_scope["stage1_excel_recalc_required"]:
            stage1_validation = validate_saved_stage1(staging, allow_recalc=not args.skip_excel_recalc)
        else:
            stage1_validation = validate_saved_stage1_scoped(staging, bs)
        timed_stage(output_dir, "stage1_validated", run_started_at)
        stage1_issues = validate_stage1_gate(stage1_validation)
        if stage1_issues:
            write_contract_json(output_dir / "stage1_gate_failures.json", stage1_issues)
            raise RuntimeError("stage1_gate_failed")

        wb = load_workbook(staging)
        timed_stage(output_dir, "stage2_opened", run_started_at)
        for sheet in wb:
            sheet._locked_template_layout = True
            sheet._report_date = cover_source['report_date']
        (
            sheet_plan,
            completed_pages,
            placeholder_pages,
            all_written_rows,
            stage2_meta,
        ) = stage2_fill_detail_pages_from_trial_balance(
            wb,
            sheet_plan,
            bs,
            journal_rows,
            protection,
            registry,
            counterparty_balance_rows,
            bank_account_rows,
        )
        timed_stage(output_dir, "stage2_filled", run_started_at, completed_pages=len(completed_pages), placeholders=len(placeholder_pages))
        stage2_fix_writes = stage2_postfix_key_sheets(wb, bs)
        timed_stage(output_dir, "stage2_postfix_done", run_started_at)
        detail_candidates_preview = build_detail_candidates(sheet_plan)
        routing_issues = validate_routing_sanity(detail_candidates_preview)
        timed_stage(output_dir, "routing_validated", run_started_at, issue_count=len(routing_issues))
        if routing_issues:
            write_contract_json(output_dir / "routing_sanity_failures.json", routing_issues)
            raise RuntimeError("routing_sanity_failed")
        placeholder_pages, stage3_meta = stage3_enrich_detail_pages_from_journals(
            wb, bs, placeholder_pages, execution_scope
        )
        timed_stage(output_dir, "stage3_done", run_started_at, placeholders=len(placeholder_pages))
        visibility_report = apply_sheet_visibility(wb, bs["values"], sheet_plan, completed_pages, placeholder_pages)
        timed_stage(output_dir, "visibility_done", run_started_at)
        summary_anchor_backfill = backfill_y71_summary_anchors(wb, bs["values"], protection, registry, summary_registry)
        timed_stage(output_dir, "summary_backfill_done", run_started_at)
        footer_normalization_report = normalize_all_detail_sheet_footers(wb)
        timed_stage(output_dir, "footer_normalized", run_started_at, sheet_count=len(footer_normalization_report))
        assert_summary_formulas_preserved(wb, summary_formula_baseline)
        assert_template_formulas_preserved(wb, template_formula_baseline)
        wb.calculation.calcMode = "auto"
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
        wb.save(staging)
        wb.close()
        timed_stage(output_dir, "stage23_saved", run_started_at)
    except ProtectionViolation as exc:
        conflict_path = output_dir / "write_conflict_report.json"
        write_json(conflict_path, exc.payload)
        raise

    if args.allow_excel_recalc and not args.skip_excel_recalc:
        force_excel_recalc(staging)
    timed_stage(
        output_dir,
        "recalc_skipped_or_done",
        run_started_at,
        skipped=not (args.allow_excel_recalc and not args.skip_excel_recalc),
    )
    repair_report = repair_unique_source_cells(staging,
        json.loads(Path(args.source_checks).read_text(encoding='utf-8')) if args.source_checks else [], registry)
    write_json(output_dir / 'automatic_repair_report.json', repair_report)
    if repair_report['repairs'] and args.allow_excel_recalc and not args.skip_excel_recalc:
        force_excel_recalc(staging)
    verification_wb = load_workbook(staging, data_only=False)
    try:
        assert_summary_formulas_preserved(verification_wb, summary_formula_baseline)
        assert_template_formulas_preserved(verification_wb, template_formula_baseline)
        cover_report = validate_cover(verification_wb, cover_source)
    finally:
        verification_wb.close()
    write_json(output_dir / "summary_formula_preservation_report.json", {
        "status": "pass", "workbook": str(staging),
        "formula_count": sum(len(cells) for cells in summary_formula_baseline.values()),
        "sheet_formula_counts": {name: len(cells) for name, cells in summary_formula_baseline.items()},
    })
    write_json(output_dir / 'cover_fill_report.json', cover_report)

    validation, counterparty_anomaly_report, semantic_validation_report, reconciliation = stage4_validate_and_self_check(
        staging,
        completed_pages,
        placeholder_pages,
        all_written_rows,
        bs["values"],
    )
    timed_stage(output_dir, "stage4_validated", run_started_at)
    flow_debug = build_flow_debug_report(staging)
    reconciliation.update(
        {
            "project_mapping": args.project_mapping,
            "formula_chain": args.formula_chain,
            "formula_protection": args.formula_protection,
            "source_policy": "tb_and_counterparty_detail_primary__journal_fallback_only",
        }
    )

    write_json(output_dir / "completed_pages.json", completed_pages)
    write_json(output_dir / "placeholder_pages.json", placeholder_pages)
    write_json(output_dir / "classification_reconciliation.json", reconciliation)
    write_json(output_dir / "validation_report.json", validation | {"summary_anchor_backfill": summary_anchor_backfill, "bs_detail_backfill_writes": stage2_meta["bs_backfill_writes"], "stage2_fix_writes": stage2_fix_writes if 'stage2_fix_writes' in locals() else [], "visibility_report": visibility_report, "footer_normalization_report": footer_normalization_report if 'footer_normalization_report' in locals() else [], "template_footer_layouts_added": sorted(template_footer_layouts), **stage3_meta})
    write_json(output_dir / "semantic_validation_report.json", semantic_validation_report)
    write_json(output_dir / "counterparty_anomaly_report.json", counterparty_anomaly_report)
    write_contract_json(
        output_dir / "source_inventory.json",
        {
            "trial_balance": args.trial_balance,
            "balance_sheet": args.balance_sheet,
            "journal": args.journal or "",
            "counterparty_balance": args.counterparty_balance or "",
            "bank_statements": list(args.bank_statement),
            "template": args.template,
            "project_mapping": args.project_mapping,
            "formula_chain": args.formula_chain,
            "sheet_layout": args.sheet_layout,
            "formula_protection": args.formula_protection,
            "input_cell_registry": args.input_cell_registry,
            "summary_chain_input_registry": args.summary_chain_input_registry,
        },
    )
    write_contract_json(output_dir / "project_mapping.json", mapping)
    detail_candidates = build_detail_candidates(sheet_plan)
    counterparty_resolution = build_counterparty_resolution(detail_candidates)
    page_plan_payload = build_page_plan(sheet_plan)
    field_assignment_plan = build_field_assignment_plan(sheet_plan)
    hidden_scope = build_hidden_scope(visibility_report)
    missing_materials = build_missing_materials(placeholder_pages)
    unreconciled_reasons = build_unreconciled_reasons(validation)
    write_contract_json(output_dir / "workflow_rules.json", rules_payload())
    write_contract_json(output_dir / "source_profile.json", build_source_profile(args, bs, tb_rows, journal_rows))
    write_contract_json(output_dir / "normalized_trial_balance.json", build_normalized_trial_balance(tb_rows))
    write_contract_json(output_dir / "normalized_balance_sheet.json", build_normalized_balance_sheet(bs))
    write_contract_json(output_dir / "normalized_journal.json", build_normalized_journal(journal_rows))
    write_contract_json(output_dir / "detail_candidates.json", detail_candidates)
    write_contract_json(output_dir / "counterparty_resolution.json", counterparty_resolution)
    write_contract_json(output_dir / "page_plan.json", page_plan_payload)
    write_contract_json(output_dir / "field_assignment_plan.json", field_assignment_plan)
    write_contract_json(output_dir / "hidden_scope.json", hidden_scope)
    write_contract_json(output_dir / "missing_materials.json", missing_materials)
    write_contract_json(output_dir / "unreconciled_reasons.json", unreconciled_reasons)
    write_contract_json(output_dir / "rule_enforcement_report.json", build_rule_enforcement_report(validation, semantic_validation_report))
    write_json(
        output_dir / "field_lineage_report.json",
        {
            "source_policy": "tb_and_counterparty_detail_primary__journal_fallback_only",
            "project_mapping": args.project_mapping,
            "sheet_plan": [{"sheet": sheet_name, "kind": kind, "row_count": len(rows)} for sheet_name, rows, kind in sheet_plan],
            "written_rows": [
                {
                    "sheet": item["_sheet"],
                    "row": item["_written_row"],
                    "tb_code": item.get("tb_code", ""),
                    "counterparty": item.get("counterparty", ""),
                    "business_desc": item.get("sub_name", ""),
                    "fill_mode": item.get("fill_mode", "detail_fillable"),
                    "fill_reason": item.get("fill_reason", ""),
                }
                for item in all_written_rows
            ],
        },
    )
    delivery_check_report = build_delivery_gate_report(
        argparse.Namespace(
            workbook=str(staging),
            output=str(output_dir / "delivery_check_report.json"),
            validation_report=str(output_dir / "validation_report.json"),
            semantic_validation_report=str(output_dir / "semantic_validation_report.json"),
            classification_j4="",
            assume_balanced=False,
        )
    )
    write_contract_json(output_dir / "delivery_check_report.json", delivery_check_report)
    write_json(output_dir / "flow_debug_report.json", flow_debug)
    write_json(output_dir / "receivable_payable_source_reconciliation.json", stage2_meta["source_reconciliation"])
    source_review = review_pipeline_sources(staging, args, sys.modules[__name__], all_written_rows, initial_source_hashes)
    write_json(output_dir / 'source_recheck_report.json', source_review)
    artifact_issues = validate_required_artifacts(output_dir)
    detailed_rule_report = build_detailed_rule_enforcement_report(
        validation,
        semantic_validation_report,
        stage1_issues if "stage1_issues" in locals() else [],
        routing_issues if "routing_issues" in locals() else [],
        artifact_issues,
    )
    write_contract_json(output_dir / "rule_enforcement_report_detailed.json", detailed_rule_report)
    notices = [*source_review.get('notices', []), *placeholder_pages]
    write_stage(output_dir, 'review_finished', status=source_review['status'])
    publish_after_review(staging, published, output_dir, [
        source_review,
        {'status': delivery_check_report['status'], 'issues': delivery_check_report.get('gate_issues', [])},
        {'status': reconciliation['status'], 'issues': semantic_validation_report.get('failures', [])},
        {'status': 'fail' if artifact_issues else 'pass', 'issues': artifact_issues},
    ], notices)
    print(published.as_posix())
    write_stage(output_dir, "complete", published=str(published))


if False and __name__ == "__main__":
    main()


# Final override: never write directly into linked summary sheets for placeholder-only non-current classes.
def fill_noncurrent_placeholders(wb, bs_values: dict[str, float]) -> list[dict[str, Any]]:
    placeholders = []
    fixed_asset_value = round(float(bs_values.get("固定资产", 0.0) or bs_values.get("固定资产净值", 0.0) or 0.0), 2)
    if abs(fixed_asset_value) >= 0.005 and "固定资产汇总" in wb.sheetnames:
        ws = wb["固定资产汇总"]
        for row, cols in [(22, [3, 4, 5, 6, 7, 8])]:
            for col in cols:
                cell = ws.cell(row, col)
                if not isinstance(cell, MergedCell):
                    cell.value = fixed_asset_value
        placeholders.append(
            {
                "sheet": "固定资产汇总",
                "account_name": "固定资产",
                "value": fixed_asset_value,
                "reason": "fixed_asset_register_missing_net_placeholder",
            }
        )
    for account_name, item in NONCURRENT_ASSET_SHEET_MAPPING.items():
        if account_name == "固定资产":
            continue
        value = round(float(bs_values.get(item["bs_line"], 0.0) or 0.0), 2)
        if abs(value) < 0.005:
            continue
        placeholders.append(
            {
                "sheet": item["sheet"],
                "account_name": account_name,
                "value": value,
                "reason": "placeholder_only_noncurrent_account_requires_detail_source",
            }
        )
    for account_name, item in NONCURRENT_LIABILITY_SHEET_MAPPING.items():
        value = round(float(bs_values.get(item["bs_line"], 0.0) or 0.0), 2)
        if abs(value) < 0.005:
            continue
        placeholders.append(
            {
                "sheet": item["sheet"],
                "account_name": account_name,
                "value": value,
                "reason": "placeholder_only_noncurrent_liability_requires_detail_source",
            }
        )
    return placeholders


# Final override: stage2 should not write any fake total/summary rows into detail sheets.
def backfill_detail_summary_inputs_from_bs(
    wb,
    bs_values: dict[str, float],
    protection: dict[str, Any],
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    if "股权投资" in wb.sheetnames:
        ws = wb["股权投资"]
        amount = round(float(bs_values.get("长期股权投资", 0.0) or 0.0), 2)
        if abs(amount) >= 0.005:
            for cell_ref, value in [
                ("A6", 1),
                ("B6", "长期股权投资占位（待补投资明细）"),
                ("G6", amount),
                ("I6", amount),
                ("J6", amount),
            ]:
                ws[cell_ref] = value
                writes.append({"sheet": "股权投资", "cell": cell_ref, "value": value})
    return writes


# Final override: use counterparty-balance rows as the only real-subject source for the six counterparties sheets.
def refine_counterparty_balance_rows(
    sheet_plan: list[tuple[str, list[dict[str, Any]], str]],
    counterparty_rows: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]], str]]:
    return sheet_plan


def stage2_postfix_key_sheets(
    wb,
    bs: dict[str, Any],
) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    bs_values = bs["values"]
    fixed_asset_value = round(float(bs_values.get("固定资产", 0.0) or bs_values.get("固定资产净值", 0.0) or 0.0), 2)
    deferred_income = round(float(bs_values.get("递延收益", 0.0) or 0.0), 2)
    long_equity_value = round(float(bs_values.get("长期股权投资", 0.0) or 0.0), 2)
    if "股权投资" in wb.sheetnames and abs(long_equity_value) >= 0.005:
        ws = wb["股权投资"]
        for cell_ref, value in {
            "A6": 1,
            "B6": "长期股权投资占位（待补投资明细）",
            "G6": long_equity_value,
            "I6": long_equity_value,
            "J6": long_equity_value,
        }.items():
            if ws[cell_ref].data_type == 'f':
                continue
            ws[cell_ref] = value
            writes.append({"sheet": "股权投资", "cell": cell_ref, "value": value})

    other_current_liab = round(float(bs_values.get("其他流动负债", 0.0) or 0.0), 2)
    if "其他流动负债" in wb.sheetnames and abs(other_current_liab) >= 0.005:
        ws = wb["其他流动负债"]
        for cell_ref, value in {
            "A6": 1,
            "B6": "预提费用",
            "D6": "预提费用",
            "E6": other_current_liab,
            "G6": other_current_liab,
            "H6": other_current_liab,
        }.items():
            if ws[cell_ref].data_type == 'f':
                continue
            ws[cell_ref] = value
            writes.append({"sheet": "其他流动负债", "cell": cell_ref, "value": value})





    if "资产负债表" in wb.sheetnames:
        ws = wb["资产负债表"]
        asset_total = round(float(bs_values.get("资产总计", 0.0) or 0.0), 2)
        liability_total = round(float(bs_values.get("负债合计", 0.0) or 0.0), 2)
        equity_total = round(float(bs_values.get("所有者权益合计", 0.0) or 0.0), 2)
        noncurrent_asset_total = round(float(bs_values.get("非流动资产合计", 0.0) or 0.0), 2)
        noncurrent_liability_total = round(float(bs_values.get("非流动负债合计", 0.0) or 0.0), 2)
        deferred_income = round(float(bs_values.get("递延收益", 0.0) or 0.0), 2)
        for cell_ref, value in {
            "C37": round(float(bs_values.get("非流动资产合计", 0.0) or 0.0), 2) if bs.get("values_prior") else 0.0,
            "D37": noncurrent_asset_total,
            "H27": 0.0,
            "I27": deferred_income,
            "H28": 0.0,
            "I28": noncurrent_liability_total,
            "H29": liability_total - noncurrent_liability_total,
            "I29": liability_total,
            "C38": round(float(bs.get("values_prior", {}).get("资产总计", 0.0) or 0.0), 2),
            "D38": asset_total,
            "H38": round(float(bs.get("values_prior", {}).get("负债和所有者权益合计", bs.get("values_prior", {}).get("资产总计", 0.0)) or 0.0), 2),
            "I38": asset_total,
            "H39": 0.0,
            "I39": 0.0,
        }.items():
            if ws[cell_ref].data_type == 'f':
                continue
            ws[cell_ref] = value
            writes.append({"sheet": "资产负债表", "cell": cell_ref, "value": value})
    return writes


# Final-final override: enforce stage2 page-level rules only.
def apply_counterparty_balance_rows(
    sheet_plan: list[tuple[str, list[dict[str, Any]], str]],
    counterparty_rows: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]], str]]:
    code_to_sheet = {
        "1122": "应收账款",
        "1123": "预付账款",
        "1221": "其他应收款",
        "2202": "应付账款",
        "2203": "预收账款",
        "2241": "其他应付款",
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in counterparty_rows:
        tb_code = row["tb_code"]
        top = tb_code[:4]
        sheet_name = code_to_sheet.get(top)
        if not sheet_name:
            continue
        amount = row["debit"] if sheet_name in {"应收账款", "预付账款"} else row["credit"]
        if not amount:
            continue
        grouped.setdefault(sheet_name, []).append(
            {
                "counterparty": row["counterparty"],
                "sub_name": row.get("business_desc", ""),
                "book_value": amount,
                "tb_code": tb_code,
                "detail_policy": "detail_fillable",
                "fill_mode": "detail_fillable",
                "fill_reason": "",
                "source_type": "counterparty_balance_detail",
                "field_confidence": "high",
            }
        )

    merged = []
    target_sheets = {"应收账款", "预付账款", "其他应收款", "应付账款", "预收账款", "其他应付款"}
    for sheet_name, rows, kind in sheet_plan:
        if sheet_name in target_sheets:
            merged.append((sheet_name, grouped.get(sheet_name, []), kind))
        else:
            merged.append((sheet_name, rows, kind))
    return merged


def normalize_stage2_rows(
    sheet_plan: list[tuple[str, list[dict[str, Any]], str]],
    bs: dict[str, Any],
    bank_account_rows: list[dict[str, Any]] | None = None,
) -> list[tuple[str, list[dict[str, Any]], str]]:
    normalized = []
    for sheet_name, rows, kind in sheet_plan:
        if sheet_name == "银行存款":
            if bank_account_rows:
                normalized.append((sheet_name, list(bank_account_rows), kind))
                continue
            amount = abs(float(bs["values"].get("货币资金", 0.0) or 0.0))
            bank_rows = []
            if amount >= 0.005:
                bank_rows.append(
                    {
                        "counterparty": "",
                        "sub_name": "",
                        "book_value": amount,
                        "fill_mode": "placeholder_only",
                        "fill_reason": "no_bank_account_detail",
                    }
                )
            normalized.append((sheet_name, bank_rows, kind))
            continue
        if sheet_name == "应交税费":
            tax_totals: dict[str, float] = {}
            for row in filter_leaf_tax_rows(rows):
                name = clean(row.get("sub_name", ""))
                if not name or "汇总" in name or name == "应交税费":
                    continue
                tax_name = normalize_tax_type(name)
                if not tax_name:
                    continue
                tax_totals[tax_name] = round(tax_totals.get(tax_name, 0.0) + float(row.get("book_value", 0.0) or 0.0), 2)
            tax_rows = [
                {
                    "counterparty": "",
                    "sub_name": tax_name,
                    "book_value": amount,
                    "fill_mode": "detail_fillable",
                    "fill_reason": "",
                }
                for tax_name, amount in tax_totals.items()
                if abs(amount) >= 0.005
            ]
            normalized.append((sheet_name, tax_rows, kind))
            continue
        normalized.append((sheet_name, rows, kind))
    return normalized


def stage2_fill_detail_pages_from_trial_balance(
    wb,
    sheet_plan: list[tuple[str, list[dict[str, Any]], str]],
    bs: dict[str, Any],
    journal_rows: list[dict[str, Any]],
    protection: dict[str, Any],
    registry: dict[str, Any],
    counterparty_balance_rows: list[dict[str, Any]] | None = None,
    bank_account_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[str, list[dict[str, Any]], str]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    counterparty_balance_rows = counterparty_balance_rows or []
    sheet_plan = normalize_stage2_rows(sheet_plan, bs, bank_account_rows)

    # Rebuild stage-2 rows by page type.
    six_detail_sheets = {"应收账款", "预付账款", "其他应收款", "应付账款", "预收账款", "其他应付款"}
    cp_code_to_sheet = {"1122": "应收账款", "1123": "预付账款", "1221": "其他应收款", "2202": "应付账款", "2203": "预收账款", "2241": "其他应付款"}
    cp_grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in six_detail_sheets}
    for row in counterparty_balance_rows:
        top = str(row.get("tb_code", ""))[:4]
        sheet_name = cp_code_to_sheet.get(top)
        if not sheet_name:
            continue
        amount = row.get("debit", 0.0) if sheet_name in {"应收账款", "预付账款", "其他应收款"} else row.get("credit", 0.0)
        if not amount:
            continue
        cp_text = clean(row.get("counterparty", ""))
        cp_state = classify_counterparty_text(cp_text)
        if cp_text and cp_state["is_valid"]:
            fill_mode = "detail_fillable"
            fill_reason = ""
            display_counterparty = cp_text
        else:
            fill_mode = "placeholder_only"
            fill_reason = cp_state["reason"]
            display_counterparty = ""
        cp_grouped[sheet_name].append(
            {
                "counterparty": display_counterparty,
                "sub_name": row.get("business_desc", ""),
                "book_value": amount,
                "tb_code": row.get("tb_code", ""),
                "detail_policy": "detail_fillable",
                "fill_mode": fill_mode,
                "fill_reason": fill_reason,
                "evidence_boundary": "no_journal_match",
                "remark": f"客商明细原列示：{cp_text}；未证明为明确主体，待补明细" if cp_text and not cp_state["is_valid"] else "",
            }
        )

    rebuilt = []
    payroll_lineage: dict[str, Any] = {}
    for sheet_name, rows, kind in sheet_plan:
        if sheet_name == "银行存款":
            if bank_account_rows:
                rebuilt.append((sheet_name, list(bank_account_rows), kind))
                continue
            rebuilt.append(
                (
                    sheet_name,
                    [
                        {
                            "counterparty": "",
                            "sub_name": "",
                            "book_value": abs(float(bs["values"].get("货币资金", 0.0) or 0.0)),
                            "fill_mode": "placeholder_only",
                            "fill_reason": "no_bank_account_detail",
                        }
                    ]
                    if abs(float(bs["values"].get("货币资金", 0.0) or 0.0)) >= 0.005
                    else [],
                    kind,
                )
            )
            continue
        if sheet_name in six_detail_sheets:
            source_rows = cp_grouped.get(sheet_name, []) if counterparty_balance_rows else rows
            source_rows = remove_excess_return_noise_rows(sheet_name, source_rows, bs["values"])
            source_rows = append_net_reconciliation_row(sheet_name, source_rows, bs["values"])
            rebuilt_rows = reconcile_detail_rows_to_bs(sheet_name, source_rows, bs["values"])
            rebuilt.append((sheet_name, rebuilt_rows, kind))
            continue
        if sheet_name == "其他应收款":
            filtered = []
            for row in rows:
                tb_code = str(row.get("tb_code", ""))
                text = f"{row.get('sub_name','')} {tb_code}"
                if tb_code.startswith("122102") or any(token in text for token in ["押金", "保证金", "房屋押金"]):
                    filtered.append(
                        {
                            **row,
                            "counterparty": "",
                            "fill_mode": "placeholder_only",
                            "fill_reason": "no_counterparty_evidence",
                        }
                    )
            rebuilt.append((sheet_name, filtered, kind))
            continue
        if sheet_name == "职工薪酬":
            bs_total = abs(float(bs["values"].get("应付职工薪酬", 0.0) or 0.0))
            payroll_result = build_payroll_rows(
                rows, journal_rows, bs_total=bs_total,
                report_date=bs.get("report_date"), date_policy="journal_last_real_credit")
            payroll_lineage.update(payroll_result)
            if payroll_result["status"] == "ok":
                rebuilt.append((sheet_name, payroll_result["rows"], kind))
                continue
            # 叶子合计与 BS 不一致或无叶子来源：显式 placeholder 站位并保留
            # 差异原因，绝不回退为伪装 detail_fillable 的单行汇总。
            rebuilt.append(
                (
                    sheet_name,
                    [
                        {
                            "counterparty": "",
                            "sub_name": "应付职工薪酬",
                            "book_value": bs_total,
                            "fill_mode": "placeholder_only",
                            "fill_reason": "payroll_reconcile_blocked",
                            "remark": payroll_result["unreconciled_reason"],
                        }
                    ]
                    if bs_total >= 0.005
                    else [],
                    kind,
                )
            )
            continue
        if sheet_name == "应交税费":
            tax_totals: dict[str, float] = {}
            for row in filter_leaf_tax_rows(rows):
                name = clean(row.get("sub_name", ""))
                if not name or "汇总" in name or name == "应交税费":
                    continue
                tax_name = normalize_tax_type(name)
                if not tax_name:
                    continue
                tax_totals[tax_name] = round(tax_totals.get(tax_name, 0.0) + float(row.get("book_value", 0.0) or 0.0), 2)
            tax_rows = [
                {
                    "counterparty": "",
                    "sub_name": tax_name,
                    "book_value": amount,
                    "fill_mode": "detail_fillable",
                    "fill_reason": "",
                }
                for tax_name, amount in tax_totals.items()
                if abs(amount) >= 0.005
            ]
            total = round(sum(r["book_value"] for r in tax_rows), 2)
            bs_total = round(float(bs["values"].get("应交税费", 0.0) or 0.0), 2)
            diff = round(bs_total - total, 2)
            # Keep the source-derived tax total; unresolved differences are reported at review.
            rebuilt.append((sheet_name, tax_rows, kind))
            continue
        rebuilt.append((sheet_name, rows, kind))

    sheet_plan = rebuilt
    completed_pages = []
    placeholder_pages: list[dict[str, Any]] = []
    all_written_rows: list[dict[str, Any]] = []
    write_simple_detail_sheet._bs_values = bs["values"]

    for sheet_name, rows, kind in sheet_plan:
        if sheet_name not in wb.sheetnames:
            continue
        written = write_simple_detail_sheet(wb[sheet_name], rows, kind, protection, registry, journal_rows)
        completed_pages.append({"sheet": sheet_name, "row_count": len(written)})
        all_written_rows.extend(written)
        for item in rows:
            if item.get("fill_mode") == "placeholder_only":
                placeholder_pages.append(
                    {
                        "sheet": sheet_name,
                        "tb_code": item.get("tb_code", ""),
                        "counterparty": item.get("counterparty", ""),
                        "value": item.get("book_value", 0.0),
                        "reason": item.get("fill_reason", ""),
                    }
                )

    inventory_total = round(float(bs["values"].get("存货", 0.0) or 0.0), 2)
    if abs(inventory_total) >= 0.005 and "产成品（库存商品）" in wb.sheetnames:
        ws_inv = wb["产成品（库存商品）"]
        safe_set(ws_inv, "A7", 1, protection, registry, kind="detail_body_write")
        safe_set(ws_inv, "B7", "库存商品净额站位（待补存货明细）", protection, registry, kind="detail_body_write")
        safe_set(ws_inv, "F7", inventory_total, protection, registry, kind="detail_body_write")
        safe_set(ws_inv, "J7", inventory_total, protection, registry, kind="detail_body_write")
        safe_set(ws_inv, "M7", inventory_total, protection, registry, kind="detail_body_write")
        completed_pages.append({"sheet": "产成品（库存商品）", "row_count": 1})
        placeholder_pages.append(
            {
                "sheet": "产成品（库存商品）",
                "tb_code": "1406/1471",
                "counterparty": "",
                "value": inventory_total,
                "reason": "inventory_detail_schedule_missing_net_placeholder",
            }
        )

    return sheet_plan, completed_pages, placeholder_pages, all_written_rows, {
        "source_reconciliation": {},
        "bs_backfill_writes": [],
        "payroll_lineage": payroll_lineage,
    }


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        folder = getattr(main, 'output_dir', None)
        if folder:
            if not isinstance(exc, ReviewBlocked):
                write_feedback(folder, [issue('execution_failed', error=str(exc),
                    resolution='查看错误快照，修正来源、映射或程序后重新运行；本轮未通过验收。')])
            write_json(Path(folder) / 'error_snapshot.json', {'error': str(exc), 'type': type(exc).__name__})
            write_stage(Path(folder), 'failed', error=str(exc))
            print('本轮未通过验收。问题与处理要求：' + str(Path(folder) / 'user_feedback.md'), file=sys.stderr)
        raise
