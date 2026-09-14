"""Safe, account-scoped explanations of persisted task failure stages."""

PHASES = {
    "planning": ("计划校验", "请核对选定文件、Skill 版本及模型配置，再重新提交。"),
    "context": ("上下文构建", "请检查当前项目的历史和记忆；保留任务编号供排查。"),
    "execution": ("执行", ("请检查资料是否可读取及模型服务连接。若已发起模型调用，"
                  "请先核对服务端任务状态，不要连续重复提交。")),
    "validation": ("结果校验", ("本轮输出不能作为已验收结果。请检查文件是否被其他程序改动，"
                   "确认后重新添加文件；不要用本轮输出替代正式审核结论。")),
}


def failure_message(store, run_id: str) -> str:
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
    label, advice = PHASES.get(phase, ("未记录", "请保留任务编号，联系管理员核对日志。"))
    return f"任务未完成。失败阶段：{label}。\n{advice}\n任务编号：{run_id}"
