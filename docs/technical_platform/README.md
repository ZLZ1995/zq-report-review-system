# ZQ 技术平台：本地工作台预览

## 当前可验证范围

这是新平台的第一阶段可运行交互预览，尚不是完整 Demo 验收包。

- 三栏工作台：项目及会话、对话及执行、文件/成果/记忆。
- 新建项目、新建会话、归档项目，重启恢复对话及预检成果。
- 添加 DOCX、XLSX、XLSM、PDF，使用现有本地解析器只读预检。
- 工作表隐藏状态与依赖污染沿用既有过滤逻辑；不保存提取正文。
- 任务输入快照、Skill版本、状态转换、文件哈希验收、协作式停止。
- 用户/项目范围查询、明确确认的项目偏好、记忆删除。
- 设置服务端地址后支持登录、首次改密、获取模型与余额并进入正式审核 Skill。
- 连接检查在后台运行，断线暂停新任务、30秒期限检查、会话撤销后保存检查点退出。
- 文件以项目副本保存，历史版本可勾选；已归档项目可恢复。

## 启动

在 Windows 双击 `scripts/start_technical_platform.cmd`，选择数据保存目录。
也可以在 CMD 中执行：

```bat
.venv\Scripts\python.exe scripts\run_technical_platform.py --data-dir D:\ZQPlatformDemo
```

连接已启动且具有受信任 HTTPS 证书的本地服务端：

```bat
.venv\Scripts\python.exe scripts\run_technical_platform.py --data-dir D:\ZQPlatformDemo --server-url https://localhost:8443/api/v1
```

地址也可通过 `ZQ_REPORT_REVIEW_SERVER_URL` 配置。以上域名端口只是示例，
不会自动启动服务或安装证书。API Key只能在服务端设置，不能填到客户端。
服务端须先完成管理员建号、模型/渠道配置及余额调整。
无服务端地址时进入离线交互预览；有地址但连接失败时不回退到离线模式。

操作：新建项目 → 添加资料 → 输入预检目标 → 执行 → 查看成果 → 关闭重开验证恢复。
当前输入内容会保存到会话，但尚未通过大模型解释任意指令；执行目标由所选 Skill 确定。
本地预检不会调用大模型、不会扣费，不能把预检结果当作正式审核意见。

## 验证

```bat
.venv\Scripts\python.exe scripts\check_technical_platform.py
.venv\Scripts\python.exe scripts\render_technical_platform_preview.py
```

快照使用人工示例数据，保存到 `artifacts/technical_platform/workspace-preview.png`。
测试使用临时文件，不接触正式业务文件。

## 尚未实现的边界

- 管理员界面、主动改密入口，以及服务端强制改密的业务接口权限门禁。
- 自然语言任务路由、服务端后台任务恢复、多轮审核、建议对话与导出迁移。
- 通用工具进程隔离与真正的文件系统权限沙箱；当前仅开放代码内审核过的只读适配器。
- 自动记忆提炼、Skill优化候选测试/审批/发布/回滚。
- 第一批预览遗留的直接路径附件未自动迁移；建议重新添加文件生成受管副本。
- 历史任务恢复、记忆跨设备同步、完整 EXE 构建与安装验收。

SQLite 数据库保存本地会话和项目偏好，应保存在当前用户可访问的目录。
本地预览使用固定身份 `local-preview`，不适用于多用户共享或正式客户环境；
联网模式使用服务端地址与用户ID组合隔离项目，不复用预览身份。
项目范围检查是应用层隔离，并非对本机管理员的保护。
