# S26 执行账本：审批桥接超时与失败关闭

## 目标

避免 GUI 审批对话框关闭、窗口切换或信号丢失时 worker 永久等待，造成“UI 卡死/任务无法停止”的假象。

## 原因与位置

`technical_platform/app.py::_ask_approval_gui` 在 worker 线程发出 Qt 信号后使用无期限 `ready.wait()`。如果 GUI 对象已销毁、窗口切换或回调未执行，模型工具调用会一直停在 awaiting approval。

## 修改

- 使用 300 秒上限等待；超时按拒绝处理（fail closed），不执行外部副作用。
- 迟到回调仍可写入本地临时 verdict，但不会重新唤醒已超时的 worker。

## 验证

- 新 Agent 全量回归基线：389 passed、9 xfailed（S25）。
- Qt 审批路径仍需在 Windows 实机执行“弹窗关闭/切换会话/超时”验收；本阶段不宣称 GUI 实机验收已完成。
