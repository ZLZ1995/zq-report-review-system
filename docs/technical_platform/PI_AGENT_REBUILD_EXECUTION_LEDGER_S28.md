# S28 执行账本：新 Agent EXE 构建

## 目标

将 S17—S27 的新 Agent、会话恢复、工具边界、取消、审批超时和模型流协议修复纳入 Windows 客户端构建产物，确认启动器、更新器和主程序均生成。

## 构建

- 构建入口：`scripts/build_technical_platform.py`。
- 构建输出：`dist/s27/`（构建目录、临时目录和历史工作区不作为业务资料目录）。
- 主程序：`dist/s27/ZQ技术平台/ZQ技术平台.exe`。
- 启动器：`dist/s27/bootstrap/ZQ技术平台启动器.exe`。
- 更新器：`dist/s27/bootstrap/ZQ技术平台更新器.exe`。
- 构建使用主工作区 Python 3.10.11 与 PyInstaller 6.21.0，构建过程正常结束，exit code 0。

## 验证

- S27 全量回归：`390 passed, 9 xfailed`。
- 构建日志：PyInstaller 三个目标均报告 `Build complete!`，未出现 error；仅有可选依赖缺失 warning（`pycparser`、数据库驱动等），不影响本项目既有运行路径。
- 产物检查：主程序、启动器、更新器文件均存在，主程序内部包含 `agent_core`、`sessions`、`tools`、`business_tools`、`builtin_skills` 等新 Agent 运行资源。

## 结论与边界

S28 的本地构建验收通过。尚未宣称真实 Windows UI、Office/WPS、联网更新和 Zeabur 联调通过；这些属于后续阶段，必须在独立验收中保留证据后才能发布。
