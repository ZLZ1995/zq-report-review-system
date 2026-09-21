# ZQ 技术平台 Kimi Code 工程交接文件

> 更新时间：2026-09-18（Asia/Shanghai）  
> 用途：供 Kimi Code 在本机继续开发、测试、构建和后续发布。  
> 安全级别：可进入仓库；本文不包含任何明文密码、API Key、JWT 密钥或发布私钥。  
> 必读：开始修改前，先完整阅读本文、`GOAL_INTEGRATED_DELIVERY_CHECKLIST.md`、`LOCAL_FEATURE_UPDATE_CHECKLIST.md` 和执行账本。

## 1. 一句话定位

ZQ 技术平台是一个 Windows 项目型智能工作台。用户以项目和分支会话为中心，用自然语言描述任务；Agent 先理解当前轮意图与附件范围，再选择已登记 Skill 或原生能力执行。评估报告审核只是平台中的一个 Skill，后续会持续加入评估明细表、工商历史沿革、财务简报、办公工作流转 Skill 和浏览器自动化能力。

平台由四部分组成：

1. Windows 客户端：项目、会话、附件、Agent、Skill、浏览器、成果和本地记忆。
2. 云端服务：账号鉴权、单设备会话、模型渠道、任务编排、余额预检、计费、发布治理和 Web 总控。
3. Skill/Harness：自然语言路由、计划、权限、工具适配、任务恢复、证据、反馈和个性化记忆。
4. 发布链路：GitHub、Windows CI、Ed25519 应用级签名、总控发布记录、客户端检查与更新、Zeabur 服务。

## 2. 当前唯一正确的施工入口

### 2.1 最新本地工作树

- 路径：`D:\ZQ-Acceptance\local-feature-checkout`
- 分支：`codex/local-platform-feature-update`
- 基线提交：`d1276a680354edf02ee5d43254d934b4f7863f27`
- 远端：`https://github.com/ZLZ1995/zq-report-review-system.git`
- 远端 `main` 于本次交接核对时也是 `d1276a680354edf02ee5d43254d934b4f7863f27`。
- 该工作树包含未提交改动和未跟踪的新文件。不得清理、重置、覆盖或用远端重新检出。

### 2.2 不要从旧目录直接施工

`D:\1\1\ai-excel-agent` 是历史主工作目录，存在大量既有未提交/未跟踪内容。它仍提供共用 Python 虚拟环境和历史资料，但不是本轮最新源码的权威施工入口。

推荐顺序：

1. 在 `D:\ZQ-Acceptance\local-feature-checkout` 查看 `git status --short`。
2. 为现有改动建立只读清单和备份补丁。
3. 只在当前分支继续；未经用户明确授权，不推送、不部署、不激活新 Release。
4. 禁止 `git reset --hard`、`git checkout -- .`、`git clean -fd`、强推和笼统 `git add .`。

### 2.3 最新本地验收 EXE

- 目录：`D:\ZQ-Acceptance\local-permission-modes-20260918-1618\ZQ技术平台`
- 主程序：`D:\ZQ-Acceptance\local-permission-modes-20260918-1618\ZQ技术平台\ZQ技术平台.exe`
- 主程序 SHA256：`3263c506d17ab95337ea9d0b499f7be11e5c68bbc3dc594a9d80a446aba27d63`
- 文件大小：`16,534,922` bytes
- 这是本机验收副本，不是已经发布到所有客户端的稳定包。

## 3. 绝对业务边界

这些规则优先于便利性，任何改动都不得绕过：

1. 原始 Word、Excel、PDF 默认只读。审核不得改原件；用户明确选择插入批注时，也只能生成副本。
2. Excel 的 hidden/veryHidden 工作表及其内容不得参加审核，也不得上传给 LLM；只有未隐藏汇总表中已经呈现的最终结果可以作为可见证据。
3. 锁定模板必须原样使用。`valuation-detail-workbook-fill` 以已更新的 `template.xlsx` 为唯一模板；不得破坏既有公式、链接、超链接和版式。成果写入模板副本。
4. 工商历史沿革 Word：表格外正文小四、首行缩进 2 字符；表格内小五、首行缩进 0。模板本体不改，生成副本。
5. 业务资料、项目数据库、审核成果和下载文件不得默认写入 C 盘。项目资料由用户选择非系统盘目录；平台自身数据固定在软件安装根目录的 `data/`。
6. 客户端不保存、不显示、不允许用户配置供应商 API Key。API Key 只在服务端总控录入并加密保存。
7. 用户只看余额，不显示 Token、单轮费用、倍率和模型价格。余额不足时禁止开始整轮任务。
8. 一个账号只允许一个客户端会话；新登录应使旧客户端退出。客户密码为 8–16 位纯数字或数字+英文字母，区分大小写，并且必须包含数字。
9. Skill 可本地安装和离线发现；只有调用大模型时必须联网并完成账号、余额和服务能力验证。
10. 浏览器是独立通用能力，不与 OA 主界面绑定。用户可手动打开，也可由 Agent 根据自然语言和 Skill 需要调用。
11. 网站凭据仅在用户同意后由 Windows DPAPI 保存；禁止进入日志、任务快照、模型上下文或仓库。
12. 平台权限模式只决定“何时请求批准”，不替代业务对象选择。文件范围、模板角色、登录账号、上传成果等仍必须明确绑定。

## 4. 已实现功能

### 4.1 客户端与项目交互

- 启动后先登录，再进入工作台；服务地址内置为 `https://zq-report-review.zeabur.app/api/v1`。
- 项目为一级容器，可创建、打开、改名、置顶、归档、恢复、从侧栏移除；移除不删除业务目录。
- 项目下支持多会话/分支、草稿隔离、任务状态、未读状态和上下文继承。
- 回车发送，Alt+回车换行。
- 当前轮附件快照与历史附件隔离，Agent 不应自动把旧轮文件带入新任务。
- 文件可从资源管理器拖入对话区。
- 模型输出和任务状态直接进入对话流，不再使用独立“成果”栏。
- 长任务可取消，受控子进程、浏览器租约和资源锁可撤销。

### 4.2 Agent、Harness 与记忆

- 自然语言理解、候选能力生成、计划确认、执行契约、工具分派、任务事件、恢复、证据和结果发布已分层。
- 路由从真实 Skill 注册表产生，不依赖用户手动选择 Skill。
- 当前轮附件、Skill 版本、规则哈希、权限和成果身份被绑定到任务。
- 项目/会话/用户记忆具备来源、版本、确认和撤回边界；不得把历史业务文件自动当作当前目标。
- 审核问题使用稳定指纹，支持跨轮 `new/persistent/resolved`、忽略、建议和多轮对话。
- 报告审核完成后应主动询问是否生成带批注副本；该询问不得遗漏，也不得直接修改原件。

### 4.3 已登记的核心 Skill/能力

- `valuation-report-review-edit` / 报告审核与只读校核
- `valuation-detail-workbook-fill` / 评估明细表生成
- `gongshang-change-history-docx` / 工商历史沿革 Word
- `financial-brief-docx` / 单页财务简报
- `office-workflow-to-skill` / 将办公流程整理为可验收 Skill
- 文件资料预检、Word 审核报告导出、批注副本、内置浏览器等原生能力
- 外部 Skill ZIP：自然语言识别安装意图、当前轮单 ZIP 绑定、清单/哈希/路径穿越/大小/依赖检查、确认、幂等安装与注册；不得执行包内任意未登记脚本。

### 4.4 报告审核

- Word/Excel/PDF 本地解析；PDF 仅作为参考资料。
- Excel 隐藏表过滤应发生在发往服务端/LLM 之前。
- 客户端通过服务端 `review-jobs` 创建、执行、查询和恢复任务；使用稳定 `client_job_id` 防止重试重复扣费。
- 服务端模型选择、余额预检、DeepSeek 优先、备用渠道切换、usage 兼容计费、冻结/结算/退款和幂等已实现。
- 多轮审核、问题卡片、忽略、建议、对话、标准 Word 审核报告和批注副本链路已有实现。

### 4.5 内置浏览器

- 可独立显示/隐藏，多标签、主页、书签、下载、弹窗、Profile 隔离和账号管理已实现。
- 浏览器可由 Agent 观察、导航、滚动、等待、点击、填写、选择、登录、下载和受控上传。
- 保存的网站账号使用 DPAPI；登录填充不等于登录成功，验证码仍由用户处理。
- 外部网站失败已区分：用户停止、普通失败、安全策略阻止和 20 秒兼容性超时；提供重试和显式系统浏览器打开入口。
- 浏览器操作有任务/页面/账号/来源/文件身份绑定和持久回执；真实 OA 全业务闭环仍需继续验收。

### 4.6 三档全平台权限模式（最新本地改动，尚未发布）

- `请求批准`：修改外部文件或使用互联网时始终询问。
- `帮我批准`：只对检测到的风险操作请求批准。当前默认。
- `完全访问权限`：在业务范围已明确的前提下，允许无需逐步确认访问互联网和计算机文件。
- 覆盖模型联网、文档生成、外部 Skill 安装、客户端更新、组合任务和浏览器动作/上传/下载。
- 切换模式会停止当前活动任务并撤销浏览器租约。
- 仍保留原件只读、项目隔离、凭据加密、当前轮附件绑定等硬约束。

### 4.7 总控与服务端

- 管理员登录、客户账号创建/禁用、密码重置、余额增减、用户倍率。
- URL+API Key 测试连接，自动发现模型列表，再由管理员从下拉菜单选择具体模型。
- 多模型/多渠道配置，DeepSeek 优先，允许备用渠道。
- 账号认证、15 分钟访问令牌、7 天刷新令牌（默认值）、单设备会话、心跳和断线处理。
- 客户端发布草稿、canary/stable/withdrawn 状态、签名清单校验和审计。
- Skill 发布治理、审核任务事件、任务取消、计费对账和 PostgreSQL 迁移。
- 当前迁移 head：`0007_skill_releases`。

### 4.8 在线更新

- 客户端版本/数据架构/协议门禁、非系统盘暂存、SHA256、大小、Ed25519 清单签名、独立启动器/更新器、健康检查、失败不切换和历史数据库备份已有实现。
- 应用级 Ed25519 签名不是 Windows Authenticode 代码签名。
- 发布私钥只允许在受控本机路径使用；绝不能复制进仓库、日志、聊天或服务器环境变量。

## 5. 最新本地改动与线上稳定版的分界

### 5.1 GitHub/公开 Release

- 仓库：`https://github.com/ZLZ1995/zq-report-review-system`
- 仓库为公开库。
- 2026-09-18 核对到 `main = d1276a680354edf02ee5d43254d934b4f7863f27`。
- 公开最新 Release：`v0.2.10`，标签提交 `e22c10e98473e4d578d2134fb443fdb9776c366f`。
- 本地源码 `CLIENT_VERSION = 0.2.10`、`CLIENT_RELEASE_SEQUENCE = 5`、`UPDATER_VERSION = 0.2.10`。

### 5.2 尚未进入 GitHub/Zeabur/Release 的本地功能

当前 `codex/local-platform-feature-update` 工作树相对基线至少包含 39 个已跟踪文件改动，以及若干新文件/Skill 资源。核心内容：

- 安装目录固定平台数据，取消浏览器打开时选择数据目录。
- Codex 式项目改名、置顶、归档、移除菜单；移除逐消息分支入口。
- 统一“能力与 Skill”目录和自动路由。
- 整合 `financial-brief-docx`、`office-workflow-to-skill`。
- 自然语言安装本地 Skill ZIP。
- 浏览器外网失败恢复。
- 三档全平台权限模式。

这些改动只在本机验收，**没有提交、推送、部署或生成公开 Release**。继续开发前先保全这批改动。

## 6. 已验证结果与不能宣称通过的部分

### 6.1 最新本地专项验收

- 本地功能清单 L01–L11 已记录完成。
- 最新 `tests/technical_platform`：920 passed。
- 限定 Ruff：通过。
- 与权限/浏览器相关的 6 个源码文件限定 Mypy（`--follow-imports=skip`）：通过。
- 冻结包源码健康检查、登录窗口、内置 Skill 发现与两项新 Skill 证明运行通过。
- 最新本机验收 EXE 的哈希见第 2.3 节。

### 6.2 较早的大范围证据

- G00–G11 执行账本记录过 1280 项完整回归（220 客户端 + 184 服务端 + 876 平台）。
- 后续又完成跨进程资源门禁、真实 PostgreSQL 钱包并发、备份恢复、GitHub CI、Zeabur 部署及 v0.2.7–v0.2.10 更新链修复。
- 这些证据是历史基线，不自动覆盖最新未提交本地改动；以 `LOCAL_FEATURE_UPDATE_CHECKLIST.md` 的本地专项结果为准。

### 6.3 仍需完成/复验

1. 把最新本地改动整理为可审阅提交；在完整回归后再决定是否推送。
2. 最新三档权限模式与两项新 Skill 尚未进入 GitHub、Zeabur 和稳定更新通道。
3. 需要独立干净 Windows 机器验证：全新安装、历史无损升级、仅 Office、仅 WPS、Office+WPS、无缓存更新与回退。
4. WPS-only 环境尚无最终实机证据。
5. Windows Authenticode 未配置；当前只有应用级 Ed25519 包签名。
6. 真实 OA 的登录、验证码、上传、下载和业务成功回执仍应按具体目标继续验收；不可把“按钮已派发”当作业务成功。
7. 多服务副本任务调度尚未正式支持；当前部署应维持单应用实例，迁移也不应由多个副本并发执行。
8. 总控、部署说明和执行账本有历史表述，个别段落已落后于当前代码；修改时以代码、迁移、测试和最新检查点交叉核实。

## 7. 本地开发环境

- 操作系统：Windows，中文路径/文件/Sheet 很多。
- 首选 shell：WSL/bash；其次 Git Bash；再次 cmd。中文场景禁止 PowerShell。
- 权威工作树：`D:\ZQ-Acceptance\local-feature-checkout`
- 共用虚拟环境：`D:\1\1\ai-excel-agent\.venv`
- 虚拟环境 Python：3.10.11。
- 系统还存在 Python 3.14.3；不要误用它替代已验证的 3.10 虚拟环境。
- CI 使用 Python 3.12（Windows 客户端和 Linux 服务端）。
- 客户端依赖参考：`docs/technical_platform/requirements-preview.txt`。
- 服务端锁定依赖：`deploy/report_review_server/requirements.txt`。
- 客户端技术栈：Python、PySide6/Qt WebEngine、SQLite、python-docx、openpyxl、pdfplumber、httpx、pywin32/COM、PyInstaller。
- 服务端：FastAPI、SQLAlchemy、PostgreSQL/psycopg、Alembic、PyJWT、Argon2、cryptography、httpx。

中文执行规则：

- 不把中文路径/中文参数传给 PowerShell。
- 出现 `?` 优先判断为字符在传输前丢失；乱码优先判断解码错误。
- 使用 `apply_patch` 修改文件，避免脚本覆盖用户已有改动。
- 所有构建/测试产物写入明确的 D 盘验收目录。

## 8. 常用开发与验证命令

在 `D:\ZQ-Acceptance\local-feature-checkout` 执行。以下命令使用 cmd，避免中文经 PowerShell 传递。

```bat
set PYTHONPATH=src
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\technical_platform -q
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_app -q
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_server -q
```

本轮最新权限/浏览器/Skill 邻域应优先跑：

```bat
set PYTHONPATH=src
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest ^
  tests\technical_platform\test_agent_permission_modes.py ^
  tests\technical_platform\test_browser_action_prompt.py ^
  tests\technical_platform\test_browser_panel.py ^
  tests\technical_platform\test_browser_task_leases.py ^
  tests\technical_platform\test_automatic_routing.py ^
  tests\technical_platform\test_local_skill_resources.py ^
  tests\technical_platform\test_new_builtin_generation.py -q
```

构建与本机证明：

```bat
set PYTHONPATH=src
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\build_technical_platform.py
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\smoke_technical_platform_exe.py
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\prove_local_builtin_skills.py
```

正式打包前必须确认 `dist/technical_platform` 中没有 `.db/.sqlite/.log/.env` 或用户资料。`package_technical_platform.py` 的产物不可覆盖同名已存在文件，版本号先在 `release_info.py` 统一更新。

## 9. 关键源码导航

- 客户端入口/UI：`src/asset_based_agent/technical_platform/app.py`
- 登录/会话：`technical_platform/login.py`、`session.py`、`connection.py`
- Agent 控制：`agent_controller.py`、`planner.py`、`harness.py`、`tool_dispatcher.py`
- 契约：`src/asset_based_agent/agent_contracts.py`、`technical_platform/execution_contracts.py`、`tool_contracts.py`
- 权限：`technical_platform/agent_permission_modes.py`、`permissions.py`、`browser_action_prompt.py`
- 项目/会话/存储：`project_catalog.py`、`project_tree.py`、`store.py`、`storage_layout.py`、`storage_preferences.py`
- Skill：`skills.py`、`skill_contracts.py`、`capability_registry.py`、`skill_installation.py`、`skill_manager.py`
- 内置生成适配：`generation.py`、`generation_worker.py`、`adapters/generation.py`
- 浏览器：`browser_panel.py`、`browser_window.py`、`browser_execution_loop.py` 及 `browser_*` 模块。
- 更新：`technical_platform/updates/`、`client_update.py`、`release_info.py`
- 服务端 API：`src/asset_based_agent/report_review_server/api.py`
- 服务端配置：`report_review_server/config.py`
- 模型/计费：`services/provider_gateway.py`、`metered_model_service.py`、`wallet_service.py`
- 审核任务：`services/review_job_service.py`、`review_job_executor.py`、`server_review_agent.py`
- Web 总控：`report_review_server/admin_web.py`、`admin_assets/`
- 数据库迁移：`deploy/report_review_server/migrations/versions/`

## 10. Skill 与模板来源

- 项目内置 Skill：`.codex/skills/`
- 当前整合的本地 Skill 源还可在 `C:\Users\94635\.codex\skills\` 找到。
- 锁定业务模板：`assets/builtin_templates/` 及对应 Skill 包内 `assets/`、`template.lock.json`。
- `valuation-detail-workbook-fill` 的最新 `template.xlsx` 是唯一模板；旧模板和自行重建模板都不可替代。
- 任何模板更新必须：先记录旧/新 SHA256；证明公式、链接、命名区域、隐藏状态和格式未被误伤；再更新锁文件、测试和打包资源。

## 11. 服务器与访问路径

### 11.1 ZQ 服务

- 公网服务根地址：`https://zq-report-review.zeabur.app`
- 客户端 API：`https://zq-report-review.zeabur.app/api/v1`
- 总控：`https://zq-report-review.zeabur.app/admin`
- 健康：`https://zq-report-review.zeabur.app/api/v1/health`
- 能力：`https://zq-report-review.zeabur.app/api/v1/capabilities`
- 当前客户端发布：`https://zq-report-review.zeabur.app/api/v1/client-releases/current`

Zeabur 标识：

- 项目显示名：`untitled`
- Project ID：`6a07c045d64413c4c61e54e6`
- Service ID：`6aa28a95a5990656aa82791a`
- Environment ID：`6a07c045e5ed304c1d851182`

部署根目录为 `/`，Dockerfile 配置：

```text
ZBPACK_DOCKERFILE_PATH=deploy/report_review_server/Dockerfile
```

### 11.2 OA

- OA GitHub：`https://github.com/ZLZ1995/OA`
- OA 前端：`https://zhongqinoa01.com/`
- OA 后端：`https://zhongqinoa.zeabur.app`
- OA 只是浏览器可访问的业务系统之一，不是客户端首页，也不与浏览器强绑定。

### 11.3 本次在线核对限制

GitHub 页面与 `git ls-remote` 已核对成功。Zeabur HTTPS 接口在本次命令行只读探针中发生 TLS 握手超时，因此本文不凭空宣称当前线上 health/capabilities 内容；继续发布前必须重新只读核对。

## 12. Zeabur 环境变量

不得把实际值写入仓库。现有代码直接读取：

- `REPORT_REVIEW_ENV=production`
- `REPORT_REVIEW_DATABASE_URL`
- `REPORT_REVIEW_JWT_SECRET`（至少 32 字符）
- `REPORT_REVIEW_PROVIDER_ENCRYPTION_KEY`（URL-safe Base64，解码后 32 bytes）
- `REPORT_REVIEW_ACCESS_TOKEN_MINUTES`（默认 15）
- `REPORT_REVIEW_REFRESH_TOKEN_DAYS`（默认 7）
- `REPORT_REVIEW_BUILD_SHA` 或镜像注入的 `REPORT_REVIEW_IMAGE_BUILD_SHA`
- `REPORT_REVIEW_ADMIN_USERNAME`（只用于首次初始化）
- `REPORT_REVIEW_ADMIN_PASSWORD`（只用于首次初始化，初始化后移除）
- `PORT`（Zeabur 注入，缺省 8000）

数据库 URL 使用 `postgresql+psycopg://...`，密码必须 URL 编码。生产数据库和加密密钥必须成套备份；更换 provider 加密密钥会导致既有 API Key 无法解密。

## 13. 账号、密钥与费用

账号用户名、密码、用途和本机发布私钥路径保存在仓库外：

`D:\ZQ-Acceptance\kimi-handoff-private\KIMI_CODE_SECRETS.local.md`

规则：

- 不得提交、上传、复制到 Issue/日志/截图或模型输出。
- 使用前先确认目标域名，禁止在非官方页面填入。
- GitHub 使用现有浏览器或 `gh` 登录会话；本文没有、也不应保存 GitHub 密码/Token。
- 供应商 API Key 只在总控管理；不要从服务端读取后带回客户端。
- 历史上曾允许测试账号累计真实模型扣费不超过 20 元；这是先前验收授权，不应自动视为未来每轮都有效。新的付费测试先向用户确认。

## 14. GitHub、CI、Release 与 Zeabur 发布顺序

1. 保全当前本地工作树：记录状态、生成补丁/备份，不清理用户改动。
2. 针对最新改动跑邻域测试、完整客户端/服务端/平台回归、Ruff/Mypy。
3. 检查 secrets、业务文件、数据库、日志、临时输出和私钥未被暂存。
4. 用明确文件清单提交到 `codex/...` 分支，推送后观察 `client-ci.yml` 与 `server-ci.yml`。
5. 服务端兼容变更先部署 Zeabur，核对 build SHA、迁移 head、health、capabilities、旧客户端兼容。
6. 构建 Windows 候选；生成普通包、托管包、元数据和签名清单；使用内置公钥复验。
7. 创建 GitHub Release，资产必须来自精确提交的成功 Windows CI，不能用本机随手替换。
8. 在总控创建草稿，先 canary；完成更新、历史保留、回退和实机验证后再 stable。
9. 激活后重新核对公开 Release、总控 current-release、客户端版本提示和服务端 build SHA。

严禁先发客户端、后补服务端不兼容接口；严禁只因 health=ok 就认为迁移、模型、计费和更新全部正常。

## 15. Kimi Code 建议的第一轮工作

1. 只读打开本工作树并确认基线、分支、远端和未提交文件。
2. 阅读：
   - `docs/technical_platform/GOAL_INTEGRATED_DELIVERY_CHECKLIST.md`
   - `docs/technical_platform/LOCAL_FEATURE_UPDATE_CHECKLIST.md`
   - `docs/technical_platform/delivery/EXECUTION_LEDGER.md`
   - `docs/technical_platform/delivery/ACCEPTANCE_MATRIX.md`
   - 本文件。
3. 运行最新权限/浏览器/Skill 邻域测试，确认本机基线仍绿。
4. 生成当前改动清单，逐文件审查，不要机械格式化整个仓库。
5. 优先补齐本地未提交改动的完整回归和可审阅提交。
6. 在用户明确同意前，不推 GitHub、不部署 Zeabur、不创建/激活 Release、不调用付费模型、不向 OA 写入。
7. 之后按“服务端兼容 → CI → EXE → 签名 → canary → 实机 → stable”的顺序发布。

## 16. 完成定义

一项工作只有同时满足以下条件才可标记完成：

- 需求和授权边界明确。
- 先有可复现失败或可验证基线，再做最小修改。
- 目标测试、邻近回归和按风险确定的完整回归通过。
- 对原件、隐藏表、模板、凭据、费用和项目数据边界复核无回归。
- 产物可定位并有哈希；发布则能映射到唯一 Git commit、CI 和服务端 build SHA。
- 真实网站/Office/WPS/更新链未实际验证的部分明确写“未验”，不得用 Mock 或单元测试冒充实机验收。

## 17. 文档可信度说明

本文件是 2026-09-18 的接续入口，不替代源码和测试。若历史文档冲突，按以下优先级处理：

1. 用户最新明确要求与安全边界。
2. 当前工作树真实代码、迁移和测试。
3. `LOCAL_FEATURE_UPDATE_CHECKLIST.md` 最新本地记录。
4. `EXECUTION_LEDGER.md` 最新日期条目。
5. 旧计划、旧 README 和旧截图。

发现冲突先记录证据并询问，不要自行抹平历史或修改业务模板。
