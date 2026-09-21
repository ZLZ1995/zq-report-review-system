"""Safe, account-scoped explanations of persisted task failure stages."""

from ..report_review_app.services.remote_auth_service import (
    BILLING_RECONCILIATION_MESSAGE,
)

PHASES = {
    "planning": ("计划校验", "请核对选定文件、Skill 版本及模型配置，再重新提交。"),
    "context": ("上下文构建", "请检查当前项目的历史和记忆；保留任务编号供排查。"),
    "execution": ("执行", ("请检查资料是否可读取及模型服务连接。若已发起模型调用，"
                  "请先核对服务端任务状态，不要连续重复提交。")),
    "validation": ("结果校验", ("本轮输出不能作为已验收结果。请检查文件是否被其他程序改动，"
                   "确认后重新添加文件；不要用本轮输出替代正式审核结论。")),
}


def safe_worker_reason(message: str | None) -> str:
    """Worker exception text is only shown when it is a short user-facing literal."""
    text = (message or '').strip()
    if not text or len(text) > 200:
        return ''
    lowered = text.lower()
    if any(token in lowered for token in ('http', 'token', 'bearer', 'api', 'key',
                                          'secret', 'password', 'traceback', '\\', '/')):
        return ''
    if not any('一' <= ch <= '鿿' for ch in text):
        return ''
    return text


def failure_message(store, run_id: str, worker_message: str | None = None) -> str:
    run = store.run(run_id)
    if run["state"] in {"running", "validating"}:
        return f"任务 {run_id} 正在执行，本次重复执行未获准；请等待原任务。"
    if run["state"] != "failed":
        return f"任务 {run_id} 未进入失败状态（{run['state']}）；请核对原任务记录，勿重复提交。"
    with store.connect() as db:
        row = db.execute(
            "SELECT detail FROM events WHERE run=? AND state='failed' ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    phase = row[0].split(":", 1)[0] if row else ""
    if row and row[0].partition(":")[2].strip() == 'BillingReconciliationRequired':
        return f"{BILLING_RECONCILIATION_MESSAGE}\n任务编号：{run_id}"
    label, advice = PHASES.get(phase, ("未记录", "请保留任务编号，联系管理员核对日志。"))
    reason = safe_worker_reason(worker_message)
    reason_line = f"失败原因：{reason}\n" if reason else ""
    return f"任务未完成。失败阶段：{label}。\n{reason_line}{advice}\n任务编号：{run_id}"


# --- K07: worker failure diagnostics (stage/class/safe code/ids only) ---
import logging as _logging
import re as _re

logger = _logging.getLogger('asset_based_agent.diagnostics')

_SECRET_PATTERNS = (
    _re.compile(r'Bearer\s+\S+', _re.IGNORECASE),
    _re.compile(r'token=\S+', _re.IGNORECASE),
    _re.compile(r'api[-_]?key=\S+', _re.IGNORECASE),
    _re.compile(r'password[=：]\S+', _re.IGNORECASE),
    _re.compile(r'Cookie:\s*[^\n]+', _re.IGNORECASE),
)


def scrub(text, limit=300):
    """Remove credential-shaped fragments and bound the detail length."""
    cleaned = str(text)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub('***', cleaned)
    return cleaned[:limit]


def log_worker_failure(stage, exc, *, request_id=None, task_id=None, revision=None,
                       server_build=None):
    """Structured failure line: no credentials, no paths, no business content."""
    from .release_info import CLIENT_VERSION
    code = getattr(exc, 'error_code', None) or '-'
    status = getattr(exc, 'http_status', None) or '-'
    logger.error(
        'stage=%s exception=%s error_code=%s http_status=%s client_version=%s server_build=%s '
        'request_id=%s task_id=%s revision=%s detail=%s',
        stage, type(exc).__name__, code, status, CLIENT_VERSION, server_build or '-',
        request_id, task_id, revision, scrub(exc))
