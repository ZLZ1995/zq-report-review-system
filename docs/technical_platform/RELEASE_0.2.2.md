# ZQ 技术平台 0.2.2

本次发布第二阶段已实现能力及第三阶段 Skill 安装管理，不代表第三阶段全部完成。

- 统一 TaskSpec、有限历史及已确认项目记忆、只读执行 Harness。
- 原子任务领取、状态隔离、失败诊断进入对话。
- 外部 Skill ZIP 校验、账号隔离持久安装、启用/停用及版本切换管理界面。
- 外部 Skill 尚未接入任务执行；不执行外部脚本、不允许未经授权修改原文件。
- 原件只读、隐藏内容排除、服务端认证与计费路径保留。

本地回归：平台 91、旧客户端 164、服务端 66，共 321 项通过。
真实付费模型及完整端到端产品验收仍待完成，不以启动检查替代。

源码启动：在 Windows 安装 docs/technical_platform/requirements-preview.txt 中依赖，
运行 python scripts/run_technical_platform.py。
打包：python scripts/build_technical_platform.py；产物为 dist/technical_platform/ZQ技术平台。
运行 EXE 必须保留同目录的 _internal 文件夹，分发时复制整个目录。
平台与旧客户端测试需设置 PYTHONPATH=src，并在无显示环境设置 QT_QPA_PLATFORM=offscreen。

服务器继续使用 deploy/report_review_server/Dockerfile；客户端模块不复制进服务器镜像。
本次客户端变更不要求新增云端密钥或数据库迁移，现有服务端业务代码保持不变。
