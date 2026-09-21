#!/usr/bin/env python3
"""Validate a user-confirmed office workflow contract before skill creation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ALLOWED_SKILLS = {"documents", "spreadsheets", "presentations", "pdf"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def validate_contract(payload: Any) -> dict[str, Any]:
    errors: list[str] = []
    questions: list[str] = []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "needs_user_input": True,
            "errors": ["工作流契约必须是 JSON 对象。"],
            "questions": ["请重新提供完整的工作流信息。"],
            "office_skills": [],
        }

    required_text = {
        "schema_version": "契约版本",
        "proposed_skill_name": "拟创建的技能名称",
        "purpose": "工作流目标",
    }
    for key, label in required_text.items():
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"缺少{label}：{key}")

    name = payload.get("proposed_skill_name")
    if isinstance(name, str) and name and not NAME_RE.fullmatch(name):
        errors.append("proposed_skill_name 只能包含小写英文、数字和连字符。")

    required_lists = {
        "triggers": "触发方式",
        "inputs": "输入材料",
        "steps": "处理步骤",
        "exceptions": "异常处理规则",
        "outputs": "输出产物",
        "acceptance_criteria": "验收标准",
        "office_routes": "办公技能路由",
    }
    for key, label in required_lists.items():
        if not _nonempty_list(payload.get(key)):
            errors.append(f"缺少{label}：{key} 至少需要一项。")

    open_questions = payload.get("open_questions", [])
    if not isinstance(open_questions, list):
        errors.append("open_questions 必须是列表。")
    elif open_questions:
        questions.extend(str(item) for item in open_questions if str(item).strip())

    confirmation = payload.get("confirmation")
    if not isinstance(confirmation, dict):
        errors.append("缺少用户确认信息：confirmation")
        questions.append("请确认上述工作流摘要是否可以据此制作技能。")
    else:
        if confirmation.get("workflow_confirmed") is not True:
            errors.append("用户尚未确认工作流内容。")
            questions.append("请确认输入、步骤、异常处理、输出和验收标准是否准确。")
        if confirmation.get("ready_to_build") is not True:
            errors.append("用户尚未确认可以开始创建或更新技能。")
            questions.append("请确认现在是否可以开始创建或更新技能。")

    proof_run = payload.get("proof_run")
    if not isinstance(proof_run, dict):
        errors.append("缺少代表性试跑计划：proof_run")
        questions.append("请提供一个真实样例任务用于试跑，或明确同意使用合成样例。")
    else:
        sample_inputs = proof_run.get("sample_inputs")
        synthetic_allowed = proof_run.get("synthetic_sample_allowed") is True
        if not _nonempty_list(sample_inputs) and not synthetic_allowed:
            errors.append("试跑没有样例输入，且用户未同意使用合成样例。")
            questions.append("请提供样例文件，或确认可以用合成样例仅验证流程结构。")
        if not isinstance(proof_run.get("expected_output"), str) or not proof_run.get("expected_output", "").strip():
            errors.append("proof_run.expected_output 不能为空。")

    office_skills: list[str] = []
    routes = payload.get("office_routes")
    if isinstance(routes, list):
        for index, route in enumerate(routes, start=1):
            if not isinstance(route, dict):
                errors.append(f"office_routes 第 {index} 项必须是对象。")
                continue
            skill = str(route.get("skill") or "").strip().lower()
            responsibility = str(route.get("responsibility") or "").strip()
            if skill not in ALLOWED_SKILLS:
                errors.append(
                    f"office_routes 第 {index} 项的 skill 无效：{skill or '<空>'}。"
                    f"允许值为 {', '.join(sorted(ALLOWED_SKILLS))}。"
                )
            elif skill not in office_skills:
                office_skills.append(skill)
            if not responsibility:
                errors.append(f"office_routes 第 {index} 项缺少 responsibility。")

    questions = list(dict.fromkeys(questions))
    return {
        "ok": not errors and not questions,
        "needs_user_input": bool(errors or questions),
        "errors": errors,
        "questions": questions,
        "office_skills": office_skills,
        "proposed_skill_name": payload.get("proposed_skill_name"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        payload = json.loads(args.contract.read_text(encoding="utf-8"))
        report = validate_contract(payload)
    except (OSError, json.JSONDecodeError) as exc:
        report = {
            "ok": False,
            "needs_user_input": True,
            "errors": [f"无法读取工作流契约：{exc}"],
            "questions": ["请提供可读取的 UTF-8 JSON 工作流契约。"],
            "office_skills": [],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

