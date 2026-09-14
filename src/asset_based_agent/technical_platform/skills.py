"""Trusted skill adapters and a read-only preflight harness."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .store import PlatformStore


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


@dataclass(frozen=True)
class SkillSpec:
    id: str
    version: str
    name: str
    capabilities: frozenset[str]


class SkillRegistry:
    def __init__(self):
        self._items: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        if spec.id in self._items:
            raise ValueError("重复 Skill ID，版本切换需要独立发布流程")
        if not spec.capabilities <= {"read_selected_files", "generate_artifacts"}:
            raise PermissionError("当前平台尚未授权文件修改能力")
        self._items[spec.id] = spec

    def get(self, identity: str) -> SkillSpec:
        return self._items[identity]


PREFLIGHT = SkillSpec(
    "review.preflight",
    "0.1.0",
    "审核资料预检（不调用模型）",
    frozenset({"read_selected_files"}),
)
REVIEW = SkillSpec(
    "report.review",
    "0.1.0",
    "评估报告审核",
    frozenset({"read_selected_files", "generate_artifacts"}),
)

DETAIL = SkillSpec('valuation-detail-workbook-fill', '0.1.0', '评估明细表生成（本地）',
                   frozenset({'read_selected_files', 'generate_artifacts'}))
HISTORY = SkillSpec('gongshang-change-history-docx', '0.1.0', '工商历史沿革生成（本地）',
                    frozenset({'read_selected_files', 'generate_artifacts'}))
BUILTINS = (PREFLIGHT, REVIEW, DETAIL, HISTORY)
GENERATORS = (DETAIL, HISTORY)


def preflight(
    store: PlatformStore,
    run_id: str,
    cancel: threading.Event,
    progress: Callable[[str], None],
    *,
    provider=None,
    output=None,
    claimed: bool = False,
) -> dict:
    """Uses the existing visibility-filtering extractor; never persists extracted text."""
    import json

    from ..report_review_app.domain.models import SourceFile
    from ..report_review_app.services.document_extraction_service import (
        DocumentExtractionService,
    )
    from ..report_review_app.services.file_role_service import classify_file_role

    snapshot = json.loads(store.run(run_id)["snapshot"])
    files = snapshot["files"]
    if not files:
        raise ValueError("请先添加审核文件")
    extractor = DocumentExtractionService()
    documents = []
    result = {"kind": "preflight", "model_called": False, "files": []}
    if not claimed:
        store.claim_run(run_id)
    elif store.run(run_id)["state"] != "running":
        raise ValueError("任务未处于执行状态")
    for index, item in enumerate(files, 1):
        if cancel.is_set():
            store.transition(run_id, "cancelled", "已在文件边界停止")
            return {"kind": "cancelled"}
        path = Path(item["path"])
        if digest(path) != item["sha256"]:
            raise ValueError(f"文件已变化，请重新添加：{path.name}")
        progress(f"正在解析 {index}/{len(files)}：{path.name}")
        source = SourceFile(
            file_id=item["id"],
            original_name=path.name,
            extension=path.suffix.lower(),
            sha256=item["sha256"],
            size_bytes=path.stat().st_size,
            round_number=1,
            original_path=str(path),
            role=classify_file_role(path),
        )
        document = extractor.extract(source)
        documents.append(document)
        result["files"].append(
            {
                "name": path.name,
                "chunks": len(document.chunks),
                "characters": sum(len(c.text) for c in document.chunks),
                "warnings": document.warnings,
            }
        )
    if provider is not None and not cancel.is_set():
        from ..report_review_app.services.privacy_filter import PrivacyChunkSelector

        progress("资料已解析，正在等待服务端模型审核；可请求停止接收结果。")
        batches = PrivacyChunkSelector().build_batches(documents)
        if not batches:
            raise ValueError("没有可上传的可见文本，无法执行审核")
        provider.set_client_job_id(f"PLATFORM-{run_id}")
        def review_progress(event):
            state = event.get("state")
            if state == "output":
                if output is not None:
                    output(event["issues"])
            elif state == "reconnecting":
                progress("连接暂时中断，正在查询原审核任务；请勿重复提交。")
            elif state == "completed":
                progress("服务端审核完成，正在接收并校验结果。")
            else:
                progress(
                    f"服务端审核进行中：已完成 {event.get('completed_batches', 0)}/"
                    f"{event.get('batch_total', '?')} 批；已等待 {event.get('elapsed_seconds', 0)} 秒。"
                )

        issues = provider.review_batches(batches, progress_callback=review_progress)
        result = {
            "kind": "review",
            "model_called": True,
            "files": result["files"],
            "issues": [item.model_dump(mode="json") for item in issues],
        }
    store.transition(run_id, "validating", "校验所有原文件保持不变")
    for item in files:
        if digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("原文件发生变化，本轮验收失败")
    store.save_result(run_id, result)
    store.transition(
        run_id,
        "cancelled" if cancel.is_set() else "succeeded",
        "审核结果已校验" if provider is not None else "预检结束；未执行模型审核",
    )
    return result
