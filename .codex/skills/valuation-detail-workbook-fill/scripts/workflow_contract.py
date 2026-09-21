from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class WorkflowRule:
    rule_id: str
    phase: str
    description: str
    enforcement: str


RULES: list[WorkflowRule] = [
    WorkflowRule("R01", "stage_order", "必须先填封面和资产负债表，再进入明细阶段", "gate"),
    WorkflowRule("R02", "stage_order", "资产负债表未平时不得进入下一阶段", "gate"),
    WorkflowRule("R03", "source", "阶段2主来源为科目余额表", "gate"),
    WorkflowRule("R04", "source", "序时账只用于阶段3补业务内容、发生日期、账龄", "gate"),
    WorkflowRule("R05", "source", "六大往来余额表仅作为主体增强来源，不得替代主流程", "gate"),
    WorkflowRule("R06", "routing", "禁止仅凭编号前缀直接落页", "gate"),
    WorkflowRule("R07", "routing", "名称优先于编号进行路由判断", "gate"),
    WorkflowRule("R08", "routing", "写入前必须做路由 sanity check", "gate"),
    WorkflowRule("R09", "sheet_write", "带连接汇总页只读", "gate"),
    WorkflowRule("R10", "sheet_write", "公式单元只读", "gate"),
    WorkflowRule("R11", "sheet_write", "只允许写合法输入位", "gate"),
    WorkflowRule("R12", "sheet_write", "placeholder_only 不得落到带连接汇总页", "gate"),
    WorkflowRule("R13", "detail", "detail_fillable 页必须先生成主体行", "gate"),
    WorkflowRule("R14", "detail", "结算对象不得使用科目层级名冒充", "gate"),
    WorkflowRule("R15", "detail", "税费页默认按税种展示", "gate"),
    WorkflowRule("R16", "detail", "无证据的结算对象必须 placeholder_only", "gate"),
    WorkflowRule("R17", "detail", "无证据的发生日期不得编造", "gate"),
    WorkflowRule("R18", "detail", "账龄只能基于发生日期计算", "gate"),
    WorkflowRule("R19", "detail", "业务内容优先来自序时账摘要/行摘要", "gate"),
    WorkflowRule("R20", "validation", "J4 不通过时不得宣称完成", "gate"),
    WorkflowRule("R21", "validation", "分类汇总差异必须输出 unreconciled reasons", "artifact"),
    WorkflowRule("R22", "validation", "detail_fillable 页必须通过语义校验", "gate"),
    WorkflowRule("R23", "validation", "counterparty=business 时失败", "gate"),
    WorkflowRule("R24", "validation", "不得出现 #REF!", "gate"),
    WorkflowRule("R25", "visibility", "in-scope detail 页必须可见", "gate"),
    WorkflowRule("R26", "visibility", "placeholder-only 非流动细分页默认可隐藏", "gate"),
    WorkflowRule("R27", "visibility", "readonly 汇总页可见但只读", "gate"),
    WorkflowRule("R28", "artifact", "必须输出 source_profile.json", "artifact"),
    WorkflowRule("R29", "artifact", "必须输出 normalized_trial_balance.json", "artifact"),
    WorkflowRule("R30", "artifact", "必须输出 normalized_balance_sheet.json", "artifact"),
    WorkflowRule("R31", "artifact", "必须输出 normalized_journal.json", "artifact"),
    WorkflowRule("R32", "artifact", "必须输出 detail_candidates.json", "artifact"),
    WorkflowRule("R33", "artifact", "必须输出 counterparty_resolution.json", "artifact"),
    WorkflowRule("R34", "artifact", "必须输出 page_plan.json / field_assignment_plan.json", "artifact"),
    WorkflowRule("R35", "artifact", "必须输出 hidden_scope.json / missing_materials.json", "artifact"),
    WorkflowRule("R36", "source", "存在正式财务报表时，资产负债表必须优先使用正式财报口径", "gate"),
    WorkflowRule("R37", "structure", "写入前必须识别合计行、固定尾部和禁止修改区域", "gate"),
    WorkflowRule("R38", "structure", "六大往来固定尾部不得修改，插入行只能发生在固定尾部上方", "gate"),
    WorkflowRule("R39", "source", "银行存款页必须使用银行对账单提取开户行和纯数字账号", "gate"),
    WorkflowRule("R40", "source", "应交税费页必须使用纳税申报表提取征税机关或说明缺失", "gate"),
    WorkflowRule("R41", "detail", "发生日期必须统一写为 YYYY/MM/DD", "gate"),
    WorkflowRule("R42", "detail", "不得将报表差额占位或其余明细合计作为最终交付项", "gate"),
    WorkflowRule("R43", "runtime", "同一成果 xlsx 禁止并发写入，保存后必须校验 zip 完整性", "gate"),
    WorkflowRule("R44", "artifact", "必须输出 source_inventory.json / project_mapping.json / field_lineage_report.json", "artifact"),
    WorkflowRule("R45", "artifact", "必须输出 preflight_report.json / preflight_gate_failures.json / delivery_check_report.json", "artifact"),
    WorkflowRule("R46", "scope", "必须先按资产负债表非零科目确定执行范围；默认不得全模板处理", "artifact"),
]


def rules_payload() -> dict[str, Any]:
    return {
        "rule_count": len(RULES),
        "rules": [rule.__dict__ for rule in RULES],
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_source_profile(args: Any, bs: dict[str, Any], tb_rows: list[dict[str, Any]], journal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trial_balance": args.trial_balance,
        "balance_sheet": args.balance_sheet,
        "journal": args.journal or "",
        "counterparty_balance": getattr(args, "counterparty_balance", "") or "",
        "company": bs.get("company", ""),
        "trial_balance_row_count": len(tb_rows),
        "journal_row_count": len(journal_rows),
        "bs_keys": sorted((bs.get("values") or {}).keys()),
    }


def build_normalized_trial_balance(tb_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return tb_rows


def build_normalized_balance_sheet(bs: dict[str, Any]) -> dict[str, Any]:
    return {
        "company": bs.get("company", ""),
        "values_current": bs.get("values_current", {}),
        "values_prior": bs.get("values_prior", {}),
    }


def build_normalized_journal(journal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in journal_rows:
        item = dict(row)
        if item.get("gl_date") is not None:
            item["gl_date"] = str(item["gl_date"])
        normalized.append(item)
    return normalized


def build_detail_candidates(sheet_plan: list[tuple[str, list[dict[str, Any]], str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sheet_name, rows, kind in sheet_plan:
        for row in rows:
            out.append(
                {
                    "sheet": sheet_name,
                    "kind": kind,
                    "tb_code": row.get("tb_code", ""),
                    "counterparty": row.get("counterparty", ""),
                    "business_desc": row.get("sub_name", ""),
                    "book_value": row.get("book_value", 0.0),
                    "fill_mode": row.get("fill_mode", row.get("detail_policy", "")),
                }
            )
    return out


def build_counterparty_resolution(detail_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in detail_candidates:
        out.append(
            {
                "sheet": item["sheet"],
                "tb_code": item["tb_code"],
                "counterparty": item["counterparty"],
                "business_desc": item["business_desc"],
                "fill_mode": item["fill_mode"],
                "resolved": bool(item["counterparty"]),
            }
        )
    return out


def build_page_plan(sheet_plan: list[tuple[str, list[dict[str, Any]], str]]) -> list[dict[str, Any]]:
    return [
        {
            "sheet": sheet_name,
            "kind": kind,
            "row_count": len(rows),
            "state": "detail_fillable" if rows else "placeholder_only",
        }
        for sheet_name, rows, kind in sheet_plan
    ]


def build_field_assignment_plan(sheet_plan: list[tuple[str, list[dict[str, Any]], str]]) -> list[dict[str, Any]]:
    return [
        {
            "sheet": sheet_name,
            "kind": kind,
            "fields": sorted({key for row in rows for key in row.keys()}),
        }
        for sheet_name, rows, kind in sheet_plan
    ]


def build_hidden_scope(visibility_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "must_show": visibility_report.get("must_show", []),
        "readonly_show": visibility_report.get("readonly_show", []),
        "may_hide": visibility_report.get("may_hide", []),
        "changed": visibility_report.get("changed", []),
    }


def build_missing_materials(placeholder_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in placeholder_pages:
        out.append(
            {
                "sheet": item.get("sheet", ""),
                "reason": item.get("reason", ""),
                "value": item.get("value", 0.0),
            }
        )
    return out


def build_unreconciled_reasons(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": validation.get("classification_j4", ""),
        "difference_hits": validation.get("difference_hits", []),
        "balance_sheet_difference": validation.get("balance_sheet_difference", 0.0),
    }


def build_rule_enforcement_report(validation: dict[str, Any], semantic_validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_count": len(RULES),
        "assets_equal_liabilities_equity": validation.get("assets_equal_liabilities_equity", False),
        "classification_j4": validation.get("classification_j4", ""),
        "semantic_status": semantic_validation.get("status", ""),
        "difference_hit_count": len(validation.get("difference_hits", [])),
        "semantic_failure_count": semantic_validation.get("failure_count", 0),
    }


def build_stage2_routing_decisions(sheet_plan: list[tuple[str, list[dict[str, Any]], str]]) -> list[dict[str, Any]]:
    rows = []
    for sheet_name, items, kind in sheet_plan:
        for item in items:
            rows.append(
                {
                    "sheet": sheet_name,
                    "kind": kind,
                    "tb_code": item.get("tb_code", ""),
                    "counterparty": item.get("counterparty", ""),
                    "business_desc": item.get("sub_name", ""),
                    "book_value": item.get("book_value", 0.0),
                    "fill_mode": item.get("fill_mode", ""),
                    "fill_reason": item.get("fill_reason", ""),
                    "source_type": item.get("source_type", ""),
                    "field_confidence": item.get("field_confidence", ""),
                }
            )
    return rows


REQUIRED_ARTIFACT_NAMES = [
    "source_recheck_report.json",
    "automatic_repair_report.json",
    "source_inventory.json",
    "project_mapping.json",
    "preflight_report.json",
    "preflight_gate_failures.json",
    "source_profile.json",
    "normalized_trial_balance.json",
    "normalized_balance_sheet.json",
    "normalized_journal.json",
    "detail_candidates.json",
    "counterparty_resolution.json",
    "execution_scope.json",
    "page_plan.json",
    "field_assignment_plan.json",
    "completed_pages.json",
    "placeholder_pages.json",
    "missing_materials.json",
    "validation_report.json",
    "semantic_validation_report.json",
    "counterparty_anomaly_report.json",
    "field_lineage_report.json",
    "hidden_scope.json",
    "unreconciled_reasons.json",
    "workflow_rules.json",
    "rule_enforcement_report.json",
    "delivery_check_report.json",
]

ARTIFACT_RULE_FILES = {
    "R28": {"source_profile.json"},
    "R29": {"normalized_trial_balance.json"},
    "R30": {"normalized_balance_sheet.json"},
    "R31": {"normalized_journal.json"},
    "R32": {"detail_candidates.json"},
    "R33": {"counterparty_resolution.json"},
    "R34": {"page_plan.json", "field_assignment_plan.json"},
    "R35": {"hidden_scope.json", "missing_materials.json"},
    "R44": {"source_inventory.json", "project_mapping.json", "field_lineage_report.json"},
    "R45": {"preflight_report.json", "preflight_gate_failures.json", "delivery_check_report.json"},
    "R46": {"execution_scope.json"},
}


DATE_TEXT_RE = __import__("re").compile(r"^\d{4}/\d{2}/\d{2}$")


def validate_delivery_gate_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the final delivery-check report against P0 hard gates.

    This validator is intentionally report-based so one-off project scripts can
    reuse the same acceptance gates without importing the full pipeline.
    """
    issues: list[dict[str, Any]] = []
    if not report.get("xlsx_zip_valid", False):
        issues.append({"rule_id": "R43", "phase": "runtime", "reason": "xlsx_zip_integrity_failed"})
    if not report.get("balance_sheet_balanced", False):
        issues.append({"rule_id": "R02", "phase": "validation", "reason": "balance_sheet_not_balanced"})
    if report.get("classification_j4") not in {"OK", "ok", "Ok"}:
        issues.append({"rule_id": "R20", "phase": "validation", "reason": "classification_j4_not_ok", "value": report.get("classification_j4")})
    if int(report.get("classification_difference_count", 0) or 0) != 0:
        issues.append({"rule_id": "R20", "phase": "validation", "reason": "classification_difference_rows_exist", "count": report.get("classification_difference_count")})
    if int(report.get("forbidden_placeholder_count", 0) or 0) != 0:
        issues.append({"rule_id": "R42", "phase": "detail", "reason": "forbidden_placeholder_rows_exist", "count": report.get("forbidden_placeholder_count")})
    if int(report.get("semantic_failure_count", 0) or 0) != 0:
        issues.append({"rule_id": "R22", "phase": "validation", "reason": "semantic_failures_exist", "count": report.get("semantic_failure_count")})
    if report.get("six_counterparty_semantic_clear") is not True:
        issues.append(
            {
                "rule_id": "R22",
                "phase": "validation",
                "reason": "six_counterparty_semantic_not_clear",
                "count": report.get("six_counterparty_semantic_anomaly_count", 0),
            }
        )
    if int(report.get("bad_date_format_count", 0) or 0) != 0:
        issues.append({"rule_id": "R41", "phase": "detail", "reason": "bad_occurrence_date_format", "count": report.get("bad_date_format_count")})
    if int(report.get("bank_account_non_digit_count", 0) or 0) != 0:
        issues.append({"rule_id": "R39", "phase": "source", "reason": "bank_account_not_pure_digits", "count": report.get("bank_account_non_digit_count")})
    if int(report.get("broken_footer_count", 0) or 0) != 0:
        issues.append({"rule_id": "R38", "phase": "structure", "reason": "fixed_footer_structure_broken", "count": report.get("broken_footer_count")})
    return issues


def validate_stage1_gate(bs_validation: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    if not bs_validation.get("assets_equal_liabilities_equity", False):
        issues.append(
            {
                "rule_id": "R02",
                "phase": "stage_order",
                "reason": "balance_sheet_not_balanced_after_stage1",
                "balance_sheet_difference": bs_validation.get("balance_sheet_difference", 0.0),
            }
        )
    return issues


def validate_routing_sanity(detail_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    forbidden_by_sheet = {
        "其他应收款": ["存货", "原材料", "库存商品", "委托加工物资", "半成品", "发出商品"],
        "应收账款": ["坏账准备", "存货", "原材料", "库存商品"],
        "预付账款": ["应付账款", "其他应付款", "预收账款"],
        "应付账款": ["应收账款", "其他应收款", "预付账款"],
        "预收账款": ["应收账款", "其他应收款", "预付账款"],
    }
    for item in detail_candidates:
        sheet = item.get("sheet", "")
        text = f"{item.get('counterparty', '')} {item.get('business_desc', '')} {item.get('tb_code', '')}"
        for token in forbidden_by_sheet.get(sheet, []):
            if token and token in text:
                issues.append(
                    {
                        "rule_id": "R08",
                        "phase": "routing",
                        "sheet": sheet,
                        "tb_code": item.get("tb_code", ""),
                        "counterparty": item.get("counterparty", ""),
                        "business_desc": item.get("business_desc", ""),
                        "reason": f"routing_conflict:{token}",
                    }
                )
                break
    return issues


def validate_required_artifacts(output_dir: Path) -> list[dict[str, Any]]:
    issues = []
    for name in REQUIRED_ARTIFACT_NAMES:
        if not (output_dir / name).exists():
            issues.append(
                {
                    "rule_id": "artifact_required",
                    "phase": "artifact",
                    "artifact": name,
                    "reason": "missing_required_artifact",
                }
            )
    return issues


def build_detailed_rule_enforcement_report(
    validation: dict[str, Any],
    semantic_validation: dict[str, Any],
    stage1_issues: list[dict[str, Any]],
    routing_issues: list[dict[str, Any]],
    artifact_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    issues = [*stage1_issues, *routing_issues, *artifact_issues]
    rule_statuses = []
    for rule in RULES:
        status = "implemented"
        if rule.rule_id == "R02" and stage1_issues:
            status = "failed"
        if rule.rule_id == "R08" and routing_issues:
            status = "failed"
        rule_artifacts = ARTIFACT_RULE_FILES.get(rule.rule_id, set())
        if rule_artifacts and any(i.get("artifact") in rule_artifacts for i in artifact_issues):
            status = "failed"
        rule_statuses.append(
            {
                "rule_id": rule.rule_id,
                "phase": rule.phase,
                "description": rule.description,
                "enforcement": rule.enforcement,
                "status": status,
            }
        )
    return {
        "rule_count": len(RULES),
        "implemented_rule_count": len([r for r in rule_statuses if r["status"] == "implemented"]),
        "failed_rule_count": len([r for r in rule_statuses if r["status"] == "failed"]),
        "assets_equal_liabilities_equity": validation.get("assets_equal_liabilities_equity", False),
        "classification_j4": validation.get("classification_j4", ""),
        "semantic_status": semantic_validation.get("status", ""),
        "issues": issues,
        "rule_statuses": rule_statuses,
    }
