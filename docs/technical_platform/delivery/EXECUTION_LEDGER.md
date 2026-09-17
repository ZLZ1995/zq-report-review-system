# 执行账本

## 2026-09-18 PostgreSQL 钱包并发验收

- 在隔离 WSL Ubuntu 24.04 中安装并启动 PostgreSQL 16.2，创建一次性 `zq_acceptance` 测试库；未连接或修改 Zeabur 生产数据库。迁移从空库连续升级到真实 head `0007_skill_releases`。
- 首次真实并发探针稳定复现缺陷：同一 `client_request_id` 的 6 个并发预占只有 1 个成功，其余 5 个因 `uq_hold_user_request` 唯一约束抛出 `IntegrityError`；证据保留在探针失败输出中。测试先行新增 PostgreSQL 专项用例后，对钱包行加锁后的请求记录进行二次核对，使并发重放返回同一 hold，不新增冻结记录。
- 修复后 PostgreSQL 专项 1/1 通过；完整探针中，同请求 6/6 返回同一 hold，两个 0.60 元请求竞争 1.00 元余额时仅一个成功，6 次并发 capture 只产生 1 条扣款流水，余额为 0.75000000。证据 `D:/ZQ-Acceptance/postgresql-wallet-concurrency.json`。
- 在同一隔离 PostgreSQL 环境执行 `pg_dump -Fc`，将源库恢复到独立库 `zq_acceptance_restore`；迁移 head 均为 `0007_skill_releases`，17 张表的表名、逐表行数和字段结构全部一致。源库未删除或降级；转储 SHA256 为 `c3a924dcf908fb1c5da080ae292d934cb0901f3e013b69b5eaf76ed41131730e`，证据 `D:/ZQ-Acceptance/postgresql-backup-restore.json`。
- 邻近计费/核对/审核任务回归 43 passed、1 skipped；完整服务端回归 205 passed、1 skipped；限定 Ruff 与目标文件 Mypy 通过。跳过项仅为未提供 PostgreSQL URL 时的默认保护，本轮真实 PostgreSQL 专项已在 WSL 单独通过。G04-03 仍保留 `doing`，因为独立客户端进程间资源锁尚未验收，不能用钱包数据库并发替代该门禁。

## 2026-09-17 build identity follow-up

- G09/G10 build identity hardening: `deploy/report_review_server/Dockerfile` and repository-root `Dockerfile` now accept `ARG REPORT_REVIEW_BUILD_SHA` and expose it as the runtime `REPORT_REVIEW_BUILD_SHA`; no JWT, provider key, or release private key is baked into either image.
- TDD evidence: Dockerfile asset tests passed 5/5 in the isolated release checkout. The local Docker Desktop Linux daemon was unavailable, so an actual image build remains pending CI/Zeabur verification.
- Server regression after the change: `tests\\report_review_server` passed 189/189 in 17.59s (one upstream httpx/Starlette deprecation warning).
- Added `.github/workflows/server-ci.yml` on the release branch: server regression runs before a Docker build, and the image build receives `${{ github.sha }}` as `REPORT_REVIEW_BUILD_SHA`. YAML parsed successfully locally; GitHub Actions execution is pending remote CI observation.
- G08-05 minimum registry implemented in the release checkout: signed manifest shape is required; admin-only draft→canary/stable/withdrawn transitions are audited; the public current-release endpoint exposes only immutable manifest metadata. Migration `0005_client_releases` is included. Isolated release checkout server regression passed 191/191.
- The registry now verifies the Ed25519 signature against the client trust root before accepting a release; the server does not import desktop-only updater modules. Both source and isolated registry tests passed 2/2; isolated server regression remains 191/191.
- Client version inspection now reads `/api/v1/client-releases/current` only when the advertised capability is present, treats HTTP 404 as no release, and fail-closes malformed metadata. Release-info tests passed 11/11 in the isolated checkout.
- GitHub Actions run 6 for commit `cf590a2` succeeded: server-tests and server-image both completed successfully in 1m05s. Two upstream Node.js deprecation warnings remain; no functional failure.

## 2026-09-17 release sync evidence

- Deployment follow-up: commit `8a19de9` corrected a release-entrypoint newline-encoding defect that caused `SyntaxError: from __future__ imports must occur at the beginning of the file` in Zeabur runtime logs. Source and isolated release entrypoints now compile successfully.
- Zeabur service `zq-report-review-system` redeployed from `main` and reached 1/1 running. Public checks returned HTTP 200 for `/api/v1/health` and `/api/v1/capabilities`; the latter exposed `review_jobs`, `review_cancel`, browser actions, and material analysis capabilities.
- Online service is now reachable for protocol smoke tests. Paid model execution, OA upload receipt, signed EXE installation, Office/WPS matrix, and online-update client acceptance remain unverified and are not marked complete.
- Online authenticated smoke test passed with authorized test account `001`: login returned HTTP 200; `/api/v1/account/balance` and `/api/v1/models` both returned HTTP 200. The access token was not printed or persisted.
- Local Windows packaging completed successfully with PyInstaller; EXE directory: `D:/1/1/ai-excel-agent/dist/technical_platform/ZQ技术平台/`. Package `ZQ-Workspace-0.2.6-Windows.zip` was validated by `ZipFile.testzip()` with 4,714 files, 281,471,702 bytes, SHA256 `1f25cbb1b7aa332e9b5457b024240e7d82c943f072b830b03b0c03214565420c`. This is an unsigned local candidate; Windows Authenticode/signature and updater publication are still blocked/unverified.
- Authorized real-model smoke test passed with account `001` and synthetic Word text only: login/precheck HTTP 200, review job create HTTP 201, execute HTTP 200, final status `succeeded`, one structured issue returned. Balance changed from 98.08 to 98.07 CNY (0.01 CNY consumed, within the authorized 20 CNY cap). No token or local file was sent.
- OA browser smoke test: authorized account `张立志` logged in successfully and reached the OA workbench. The workbench currently exposes no existing test project; no project was created without explicit project identity/creation authorization, and no upload was attempted. OA upload receipt therefore remains pending on a named test project.

- Local release candidate was rebuilt in the isolated checkout `D:/ZQ-Acceptance/release-checkout` from the explicit 550-file manifest. The final staged set was 344 changed/added files; no user working-tree files were staged.
- Release checkout targeted tests passed: 200 passed, 1 warning, exit 0 (`D:/ZQ-Acceptance/release-checkout-tests2`). The earlier full local regression remains 1280 passed (`D:/ZQ-Acceptance/r-3f89ea42c59140d8a3`).
- Secret-pattern scan returned no match outside tests. Staged diff was checked after rebuilding the checkout; the first temporary copy was discarded because a formatting helper had written literal `\\n` text, so it was never committed.
- GitHub branch pushed successfully: `codex/platform-sync-20260917`, commit `b43dc39`, remote `origin` = `https://github.com/ZLZ1995/zq-report-review-system.git`. Main was not overwritten. Zeabur has not been switched or redeployed yet; online `/api/v1/capabilities` remains 404 on the old Release 0.2.5 deployment.
- First Zeabur deployment of `b0ae89e` built but crashed at startup with `ModuleNotFoundError: asset_based_agent.agent_contracts`; the runtime log is retained as failed evidence. The Dockerfile was changed to copy the complete shared `src/asset_based_agent` package, guarded by `test_dockerfile_runtime_assets.py`; server tests passed 185/185 in both source and release checkout. Fix commit `1b5ee9c` was fast-forwarded to `main` and the release branch; redeployment is pending verification.
- The second deployment of `1b5ee9c` reproduced the same import failure, proving the Zeabur service was not honoring the configured nested Dockerfile path. A root `Dockerfile` fallback was added and tested (2/2 asset tests), then commit `e2b8f4a` was fast-forwarded to `main` and the release branch. The service is currently paused/crash-looping; redeploy must be triggered and its runtime logs must pass before claiming online readiness.

启动日期：2026-09-16。目标 active；未发布、未部署。所有passed必须附验证证据。

## 当前检查点

- Zeabur只读核对：服务 `6aa28a95a5990656aa82791a` 绑定 `ZLZ1995/zq-report-review-system`，当前运行部署显示 `Release 0.2.5: metered material analysis and automatic source classification`；源码当前能力接口应在新版本中存在，但线上404，确认为旧部署不是当前协议。已为本地添加同名origin只读定位；`git ls-remote`可读到远端main `d63628c68fbb895103fca1ef7d344145341660ad`，但拉取对象时网络在TLS关闭阶段中断（RPC/curl56、early EOF），未改远端、未推送、未重新部署。继续发布前必须在稳定网络/已验证checkout下比较白名单和提交差异，禁止直接覆盖main。

- 线上/本地协议差异确认：源码 `api.py` 定义 `/api/v1/capabilities`，包含 browser_generated_download、review_jobs 等能力；对线上 `https://zq-report-review.zeabur.app/api/v1/capabilities` 的只读请求返回404，而 `/api/v1/health` 为ok。当前git remote无输出，不能把本地提交直接映射到GitHub/Zeabur，也未执行推送或部署。该差异阻断G09/G10真实联调，但不影响继续本地测试；需先取得/核实发布仓库映射和Zeabur部署权限，再备份并部署兼容版本。

- 线上只读健康探针：`https://zq-report-review.zeabur.app/api/v1/health` 返回 `{"status":"ok","service":"report-review-server"}`；根路径 `/health` 与 `/api/v1/capabilities`、`/api/v1/openapi.json` 返回404，不能据此推断版本、迁移或能力一致。未发送认证凭据、模型调用或业务写入；服务端线上部署仍需用受保护管理入口核对构建SHA/schema/环境，不能以健康状态代替G09/G10验收。

- 额度恢复后续接完成：定向回归57项通过（D:/ZQ-Acceptance/quota-reset-targeted，56.80秒）。随后完整回归session4949 exit0：220客户端+184服务端+876平台=1280通过，证据D:/ZQ-Acceptance/r-3f89ea42c59140d8a3，平台日志/运行器已校验JUnit。该全量包含登录提交固定脚本、下载登录组合范围及宿主回执；当前无活动测试。仍未真实网站提交登录、验证码接管、OA业务回执、Office/WPS实机、签名更新、EXE/GitHub/Zeabur发布；目标未完成，G06仍有真实整链门禁。无付费模型调用和外部写入。

- 登录提交固定脚本地基：browser_login_scripts.fill_script新增默认false prepare_submit；仅显式准备时在隔离世界保留60秒单次DOM票据。submit_script复核nonce/origin/form目标和模式/账号密码未变/唯一原生submit button/表单有效性，调用原生requestSubmit，仅返回dispatched，不返回凭据或认证成功。默认填充仍不提交。真实WebEngine合成HTTPS-base测试先复现缺失脚本、额外input-submit歧义漏检、HTML无效仍报派发三类红灯后修复；14脚本/TrustedLogin/NativeTaskLogin邻近通过（D:/ZQ-Acceptance/login-submit-final，session44377 exit0，12.13秒），源码Mypy与限定Ruff通过。此脚本尚无生产调用，未接独立提交许可/原生确认/Agent协议/认证回执；不得把原login填充工具改成隐式提交。当前无活动测试，最新全量1271，后续增量未新全量；无真实网站提交/费用/发布部署。下一步建立明确提交许可及生命周期撤销，再接UI/协议和SPA登录兼容，验证码留用户。

- 组合范围核查：NativeTaskLogin/TrustedLogin只填已同意使用的保存凭据，不提交登录，也不证明认证成功；原下载完整性与回执重复allowlist误拒绝含login任务。新增真实已授权login+download fixture；初始fixture试图running重新授权被正确拒绝，已改创建时传actions，随后在下载scope门禁稳定红灯。统一DOWNLOAD_DELIVERY_ACTIONS允许原生login填充，仍排除click/fill/select/upload；这是文件交付核验不是登录成功回执。35关联通过（download-login-green，session26836 exit0，24.42秒），另15完整性/有效已授权写范围拒绝测试通过（download-login-boundary，session2187 exit0，11.10秒，有重叠不相加）；2源码Mypy/限定Ruff通过。当前无活动测试；最新全量仍1271，反馈文案及本次范围增量晚于全量。登录提交/验证码接管/认证结果及真实组合整链仍需实现验证，不把填入密码或手动确认文件当身份验证。无费用/上传/打包推送部署。

- 当前无活动测试。session52260已exit0：220客户端+184服务端+867平台=1271完整通过；证据r-bb1899d077a84578b134d9d34a661d57，平台459.91秒，runner核对JUnit。此前运行中条目均为历史。随后修复下载成功对话文案：明确本地完整性校验及用户确认，不代表网站写入成功；1红2绿先复现，修后7专项/邻近通过（D:/ZQ-Acceptance/download-feedback-green，session68838 exit0，16.34秒），新测试Ruff通过。该文案改动晚于1271全量，尚未再全量。后续重点为登录后下载组合范围/实际浏览器整链及OA业务回执；仅readonly+download不能替代全部目标。无费用、上传、发布或部署；G06仍doing，目标active。

- 续接验证等待：session52260通过write_stdin确认仍存活；客户端220、服务端184已通过，平台日志推进到16%之后，未有终态。仍使用r-bb1899d077a84578b134d9d34a661d57；无重启、源码保持冻结。只读审查app.show_browser_result发现下载确认仍显示泛化成功文本，下一步应加入“本地完整性+用户确认，不代表网站写入成功”的准确反馈和测试；还须验证登录后下载等组合任务，不能把仅readonly+download范围当全部浏览器验收。当前为verified wait，最近完整基线仍1249，未发布部署。

- 下载交付已接GUI/宿主：browser_download_completion_ui新增后台完整性worker等待、活租约/上下文guard及原生确认窗口（目标/来源/文件名/大小/SHA，默认不确认，120秒到期）；取消后等worker实际退出，不将线程挂在可销毁窗口下。browser_window按download范围接该验证，混合写范围仍由完整性层拒绝。BrowserTaskHost仅接受结构化download回执并复核持久文件清单/身份；保留只读回执及拒绝裸True。worker模块缺失、dialog缺失、宿主拒绝正确回执均先红后修。16专项/邻近通过（D:/ZQ-Acceptance/download-host-green，session43364 exit0，26.43秒），3源码Mypy及限定Ruff通过。当前完整回归session52260正在运行，证据D:/ZQ-Acceptance/r-bb1899d077a84578b134d9d34a661d57；源码冻结，续接轮询该句柄，未获结果不记通过。最近完整通过仍1249。真实OA业务回执、关闭实窗整链及云端/发布仍未验，不代表G06阶段完成；无费用/外部上传/发布部署。

- 本轮进度核实：目标仍active，未打包/推送/部署；最近完整回归1249，不把G06局部实现认作整阶段完成。新增browser_download_completion.py：严格结构化下载回执绑定task/goal/summary/evidence与文件ID/SHA/身份/origin；接收原生worker清单，确认前后复核当前账号授权、running、快照、上下文和本地文件身份，拒绝取消/撤销/替换/清单变更及跨任务/来源。6缺失模块红灯后实现；33专项及邻近通过，D:/ZQ-Acceptance/download-confirm-verified（session65910 exit0，19.86秒），源码Mypy通过、限定Ruff通过。该模块尚未接BrowserTaskHost/原生确认窗口及worker生命周期，不代表整链下载成功，后续不能直接接受模型回执。下一步接UI/宿主并测取消等待线程退出，再全量。无活动测试、无真实费用/上传/发布。OA具体写入与字段展示、签名保管和生产备份范围仍需明确。

- 下载交付完整性层：新增browser_download_integrity.verify_download_delivery，仅活授权/当前账号/running且readonly+download范围；读取本任务持久成果与来源，逐文件可取消完整SHA和文件身份核验，末尾复核授权/快照/记录及全部文件身份，返回不含路径的task/goal摘要/文件清单，不包含成功标记。browser_download_artifacts新增轻量check_download_identity供后续确认后复查；browser_download_worker新增DownloadDeliveryWorker后台执行且失败不外泄异常。8初始红灯、哈希后替换漏检红灯、worker缺失红灯均复现后修复。25专项/邻近通过（D:/ZQ-Acceptance/download-delivery-worker-green，session14372 exit0，19.42秒），3源码Mypy和限定Ruff通过。当前无活动测试；新完整性层尚未接用户确认/BrowserTaskHost终态，不声称下载任务完整验收；最新全量仍1249。下一步接确认UI/取消等待线程退出/宿主结构化回执并验证，再跑全量。OA权限待回复，无实际外部写入、费用、发布部署。

- 按钮下载协议轮完整回归session37186已exit0：220客户端+184服务端+845平台=1249通过，D:/ZQ-Acceptance/r-97c7b9980fb141529a91faef14dbe23a，运行器已校验JUnit。当前无活动测试；此前“运行中”条目已被本条取代。下一步实现下载任务独立交付回执（仅只读+download范围、后台完整性复核、用户目标/文件确认、宿主结构化验证）；不与OA上传回执混同，不放宽写任务确认。OA适配与空槽合成上传授权仍待回复，无生产修改、费用或发布。

- 完整回归session37186当前仍存活，客户端220/服务端184已通过，平台.log持续推进，未获终态，不重复启动。冻结源码期间只读复核browser_completion.py发现完成校验仅允许observe/navigate/scroll/wait；下载已有成果回执仍不能走成功确认。下一项可独立推进：仅readonly+download范围的结构化文件交付回执，绑定当前账号/任务/文件ID/SHA并在后台重新验文件，不包含upload/click/fill/login等写范围；明确不证明内容正确或网站上传成功。完成该门禁需专项与整链证据，不能直接放宽ReadonlyReceipt。OA可见版本字段适配及007空槽合成上传已再次提出精确申请，未获答复，其他本地工作可继续。

- 当前完整回归session37186，证据D:/ZQ-Acceptance/r-97c7b9980fb141529a91faef14dbe23a；已启动未终态。冻结源码，续接先轮询同一句柄，不重复启动；最近完整通过基线仍1225。按钮协议新增须以本轮最终JUnit为准。

- G06按钮下载协议/循环已接线：BrowserStepRequest新增默认false/序列化省略的strict generated_downloads，仅download范围可启用；共享验证只有显式能力时接受button。服务端声明browser_generated_download并更新提示；客户端协商缺能力降至原有link-only，请求副本不改调用者，按降级请求校验恶意按钮响应。NativeTaskDownload声明支持，循环仅有原生适配器/授权download时广告能力。OpenAPI说明同步。先服务端1红灯/客户端2红灯，最终28服务端、17客户端、20平台循环/真实按钮/工厂、12持久回执专项通过（generated-server-green/generated-client-verified/generated-platform-green/generated-receipt-verified）；3源码Mypy及限定Ruff通过，未声称api.py/remote_auth全文件既有静态债务清零。HTTPS blob持久来源及原链接均验证。实际OA、完整租约/确认整链及业务版本回执仍未验，不是G06完成；下一步完整回归后补实际对象核验。无扣费/真实上传/打包/推送/部署。

- 内联按钮红灯根因已确认并修复测试fixture：鼠标点击同样失败，因此不是隔离脚本独有；DiagnosticPage捕获明确异常`URL.createObjectURL is not a function`，inline处理函数已是function且document.readyState=complete。内联作用域中的document.URL遮蔽全局URL构造器；测试HTML改显式window.URL，不改产品安全策略或派发方式。保留inline/listener×isolated/mouse四种真实WebEngine对照，全部通过；连同观察器/原生下载/持久记录共34通过（D:/ZQ-Acceptance/button-handler-fixed，session49817 exit0，16.72秒）。下方inline失败条目为历史定位，不再是当前失败。尚需按钮能力共享协议/服务端提示/客户端能力协商、实际Agent整链及OA回执；最新全量仍本轮前1225，未发布。当前无活动测试。

- G06按钮下载接线doing，当前有明确未通过用例：NativeTaskDownload区分按钮，Observer原生下载门禁确认/复核后通过before_dispatch开启一次捕获，再固定隔离脚本点击；默认任务blob仍拒绝，实际资源绑定源页面+下载动作回执，download_origin及持久记录支持HTTPS blob。不向模型开放按钮（共享validate_browser_step仍仅link），能力/服务端协议尚待联动。4原生红灯+1观察器红灯及许可过早启用红灯均复现，30原生/观察器/持久记录通过（button-observer-green），5源码Mypy/限定Ruff通过。
- 真实WebEngine对照：D:/ZQ-Acceptance/button-handler-comparison，session2518 exit1，1通过1失败。addEventListener主世界处理函数在隔离固定动作后实际生成/下载内容正确；HTML inline onclick未执行（诊断links=0），固定动作却返回dispatched。MouseEvent派发对照同样未执行，已撤回该实验改动，保留node.click。不能据此宣称所有网页点击失败或已确定底层原因；下一步核对内联处理函数初始化/世界边界与真实鼠标输入对照，保留失败断言，不跳过、不开放模型或发布。test_browser_blob_webengine当前有红灯，最新1225全量仅为本轮前基线；无活动测试/付费/上传/发布部署。

- G06生成文件下载接收：browser_download_controller仅接收当前HTTPS页面同源blob，保存框前后校验来源，传输/交付阶段页面变化取消；TaskDownloadPermission新增默认false的allow_blob，现有Agent直接下载仍不开放。3项失败先复现，32专项/邻近通过（D:/ZQ-Acceptance/blob-download-verified，session67543 exit0，19.41秒），限定Ruff及1源码Mypy通过。真实WebEngine合成页面blob内容一致；产品整窗setHtml被安全入口拒绝导致初始探针超时，未放宽生产策略，改独立WebEngine组件证明接收，原整窗HTTP下载另通过。此轮不是实际TLS/OA按钮整链，不包含Agent点击捕获或附件回执，尚未新增全量。最新完整基线1225，当前无活动测试，无付费/外部上传/发布部署。下一步接Agent按钮生成下载的一次许可/页面动作及来源持久化，再做业务附件核验。

- 完整回归session46661已exit0：217客户端+183服务端+825平台=1225通过，证据D:/ZQ-Acceptance/r-ef7bb0e381ee4cee850f702c324be3e4，平台423.45秒，运行器已核对JUnit。无活动测试；后续进入按钮生成blob下载兼容，不把下载来源绑定当实际业务回执。未上传OA/扣费/发布部署。

- 当前完整回归session46661：D:/ZQ-Acceptance/r-ef7bb0e381ee4cee850f702c324be3e4；客户端217、服务端183已通过，平台仍运行，尚不能记整轮通过。源码冻结，续接先轮询该句柄/检查JUnit，不重复启动；本轮新增来源绑定不是网站业务成功判定。

- G06下载回读来源绑定增量：DownloadArtifacts新增兼容旧记录的StoredDownload/provenance，原生下载授权摘要绑定source_url，保存仅origin/target_key/resource_sha256，不存来源URL明文。NativeTaskDownload在授权和最终保存均使用原生页面来源；页面变化仍拒绝。旧下载无provenance，不自动升级为业务回执；不支持的OA页面仍允许普通下载但不生成对象证明。3项失败先复现，22项下载保存/原生下载/交付/目标键专项通过（D:/ZQ-Acceptance/download-provenance-green），2源码Mypy通过。该证据仅绑定来源页面及文件，不证明工单/轮次/当前版本，也不自动把unknown变成功；真实OA读回和业务回执尚未完成。全量基线仍1211，当前无真实上传、费用、发布、部署。

- G06目标绑定/副作用确认：browser_upload_target.py从原生当前HTTPS URL生成target_key，模型不能提交该字段；OA /projects/{id}/flow按项目保守绑定，展示query/fragment变化或模型标签改名不能绕过同会话同成果防重，未把项目ID当工单ID。其他站点仅精确页面身份，尚非通用语义对象识别。NativeTaskUpload已接线，UploadScope/授权payload包含target_key；授权及commit事务均检查旧unknown，旧记录无稳定目标时不允许升级换key重传。schema10 metadata兼容新增可选target_key。OA原生确认新增版本替换风险和第二勾选，不授权提交审核/审批/删除。此前6目标红灯、旧记录绕过红灯、OA确认红灯均复现；最终20目标/授权/历史/确认通过（upload-target-final），此前6原生WebEngine/worker/确认邻近通过（upload-target-native），4源码Mypy及限定Ruff通过。无活动测试，增量尚未新全量；工单/轮次和实际业务回执仍未接通，不能标记G06完成。

- G06 OA回执接入已完成源码核查，新增OA_UPLOAD_RECEIPT_AUDIT.md。独立只读clone提交34c75e5a1fd8001771569bcc28fd506f68e0995b（Windows Git clean），未改OA。发现REPORT_ZIP上传会替换同工单/阶段当前版本，POST提交后返回持久id但无SHA/幂等参数；列表包含历史，下载可用于内容校验；项目ID不能当工单ID。此证据改变接线方案：必须固定稳定业务对象、区分新增/替换授权、查询后下载比对，不得仅凭网页提示成功或抽取网站Token实现API代理。真实项目范围仍待确认，未执行上传。当前无活动测试，最近全量1211；上传历史schema10等后续增量尚未新全量。

- 最新邻近session81421 exit0：10项上传历史/下载交付/host/完成回执通过（upload-history-neighbors，23.02秒），包含v9备份迁移、旧记录metadata为空、HTML标签不执行和额外字段拒绝。无活动测试。下一步继续业务对象稳定标识及网站实际回执核对；不可将本地unknown记录当远端成功证据。

- G06上传未知记录展示增量：新增browser_upload_history.py，当前账号授权查询上传尝试及HTML转义展示；schema10仅添加nullable metadata，记录origin/已确认对象标签/文件名/大小/SHA，不保存本地路径或网页凭据；新记录在commit前与unknown原子保存。app对所有任务渲染上传记录，不依赖终态result存在，因此崩溃/取消后重新打开会话可看见“上传结果待核对”。旧schema9记录不虚构元数据，迁移保留unknown。2失败测试先红（upload-history-red），25来源授权/迁移/界面测试通过（upload-history-green）；3源码Mypy通过，限定Ruff通过。该功能只有提示与可追溯状态，不提供绕过防重的重传/清除按钮，不代表网站业务回执验收。最新完整基线仍1211，增量尚未新全量。

- 最新专项session90608已exit0，host/completion/execution_loop共9通过（receipt-required-green，31.50秒）；验证裸True拒绝、合法结构化只读回执成功、证据错配/撤销/取消拒绝和循环行为。当前无运行中的测试，下一步进入上传未知记录的可见恢复和业务回执接线，不需再次轮询旧句柄。

- 2026-09-17完整回归session18796 exit0：217客户端+183服务端+811平台=1211通过；D:/ZQ-Acceptance/r-b490abafc0904ea09da54cae74256ca3，平台日志465.32秒。输出落盘后的整轮已完成，保持600秒限制。此为下述终态回执收紧之前的完整通过基线。

- G06终态门禁收紧：原BrowserTaskHost允许verifier返回裸True直接succeeded，无法记录对象/证据绑定。test_browser_task_host改为拒绝布尔成功后在旧实现稳定红灯（receipt-required-red）；删除该兼容支路，仅已验证结构化回执可成功；合法只读回执路径保留，写回执仍待实现。限定Ruff通过，当前专项session90608正在验证host/completion/execution_loop，完成前不得记通过；这不是业务上传闭环完成。

- 最新续接：session18796经多次实际轮询仍存活；report_review_app217和report_review_server183已由运行器报告通过，平台.log持续增长且尚无终态，属于verified wait。没有新启动第二份测试，源码保持冻结；输出重定向后只在终端报告分套摘要，详细进度必须读r-b490abafc0904ea09da54cae74256ca3/technical_platform.log，不以终端暂时无输出推断卡死。G06后续仍是未知上传记录恢复与业务回执；未标任何整阶段完成。

- 2026-09-17回归运行器修复：session65986句柄已不存在，检查r-4cf03ed3b1434103aec272102bd89e25完整XML发现217客户端/183服务端零失败，平台tests778且internal error1，pytest terminalwriter.flush抛OSError errno22，不能算通过。故障层为测试执行输出，不是已定位的业务断言失败；造成终端句柄异常的外部原因未证实。新增失效输出模拟红灯，修复subprocess stdout/stderr直写每套独立.log并将announce设为最佳努力；保留600秒限制、非零退出短路及XML完整性门禁。6项运行器测试通过（runner-output-green），限定Ruff通过。没有删弱业务测试。

- 当前新完整回归session18796，D:/ZQ-Acceptance/r-b490abafc0904ea09da54cae74256ca3；详细输出在各套.log中。源码冻结，续接先查同一句柄/日志及JUnit；不得把运行器专项通过当全量通过。旧1199仍为最近完整通过基线，G06业务回执及恢复入口待继续，无生产变更或付费调用。

- 2026-09-17续接审计：上一轮为实际进展（schema9及红绿/竞态验证），本轮确认完整回归session65986仍存活持续输出，客户端217、服务端183已通过，平台运行中无最终结果；保持源码冻结。只读复核browser_completion.py/browser_task_host.py/browser_execution_loop.py：目前独立结构化回执仅支持只读范围；上传dispatched不代表网站持久保存；host仍保留原生verifier布尔True兼容支路，后续业务成功接线应替换为任务/对象/成果/证据绑定的结构化核验，不能依赖模型自报成功。未对生产或OA写入。

- G06下一组实施边界：先为unknown上传记录提供账号隔离查询和恢复显示，再引入可信业务回执与结构化终态校验；对象不能只靠模型任意标签判断，须核对实际站点对象；回执至少绑定来源任务与成果SHA、站点对象、网站记录标识和当前页面证据。没有回执保持待核对，不自动清除防重记录。需测试刷新/重启/改标签/同名文件/跨账号/并发/取消后实际已上传，真实OA项目范围确认后才能进行写入验收。

- 2026-09-17 G06持久防重增量：新失败用例证明UploadAuthorization重建且page/field变化后可重复消费（upload-restart-red，1失败5通过）。增加本地schema9 browser_upload_attempts，绑定账号/项目/会话/环境/origin/对象标签/成果SHA的操作摘要，在网页commit前持久记录unknown；唯一键阻止竞态重复，重启可查询拒绝，未增加自动清除或伪成功入口。23授权/迁移测试通过（upload-restart-race），13真实WebEngine/SPA/worker/transfer邻近通过（upload-restart-neighbors），限定Ruff及2源码Mypy通过。局限：对象仍依赖已确认标签，业务回执核对及用户可见恢复入口尚待完成；不能宣称端到端防重验收。

- 当前完整回归session65986已启动，证据D:/ZQ-Acceptance/r-4cf03ed3b1434103aec272102bd89e25；保持源码冻结，下一步先轮询，不能记为通过。前述1199仍为最近完整通过基线。无真实模型扣费、OA上传、EXE打包、GitHub提交或生产部署。

- 2026-09-17完整回归session36815 exit0：217客户端+183服务端+799平台=1199通过，证据D:/ZQ-Acceptance/r-02a59ce0411a4057bdae2742131d1602；平台369.94秒，仍使用600秒门槛。该基线在下述SPA组件适配之前，适配尚未重新全量。无活动测试句柄。

- G06真实OA只读发现并修复通用组件兼容：进入007“实验项目”对应/projects/20/flow初次暂无数据，控制台Network Error，单次重载恢复，未修改OA。上传区实际为可见role=button容器+一个type=button按钮+一个display:none文件框，外层form无method/action属性。独立合成探针修前file_controls=[]红灯；新增browser_file_control共享固定策略，仅显式上传观察允许识别该唯一绑定；普通隐藏容器/歧义/submit按钮排除，禁用或不安全form展示为禁用并在执行再次拒绝。默认SPA表单不作原生提交，仅投递已授权文件change事件；跨域、显式GET、页面/对象变更仍拒绝。原生visible文件和POST流程保留。28项通过：20脚本/真实链/观察邻近（spa-upload-neighbors-fixed）+8真实SPA正负例（spa-component-verified）；限定Ruff及3源码Mypy通过。证据根D:/ZQ-Acceptance，探针已纳入tests/technical_platform/probes/spa_upload.py。禁止将这一步当真实OA上传回执验收；目标项目写入确认仍待回复，未上传/保存密码/推动流程，无API扣费或发布部署。

- 下一步：持久上传尝试/未知状态恢复及业务回执接入；真实OA允许范围确认后以产品客户端执行合成上传（Codex浏览器只读核查不能代替产品验收）；继续检查普通非OA站点。最近SPA增量只完成专项/邻近，下一组接线完成后全量验证。

- 当前活动完整三套回归session36815，证据根D:/ZQ-Acceptance/r-02a59ce0411a4057bdae2742131d1602；已启动，尚无最终结果。下一轮先轮询该句柄，保持源码冻结，不重复启动。OA浏览器tab6已markHandoff，登录/workbench；007项目合成上传授权等待回复，未执行上传。

- 2026-09-17平台耗时诊断session56792已exit0：798 passed in363.69s，JUnit D:/ZQ-Acceptance/platform-duration-diagnostic.xml；最慢单项9.37秒，未复现前次600秒超时。不能据此猜测具体机器负载根因；保留原600秒门槛，重新执行完整三套。真实上传探针已移入tests/technical_platform/probes/native_upload_webengine.py，新增test_browser_native_upload_webengine.py常规回归，1项10.16秒通过、限定Ruff通过（upload-webengine-regression）。新探针使用真实页面/观察器/上传worker/SQLite，租约与host为测试替身，仍非实际网站业务回执证明。当前无生产变更，API0元。

- 2026-09-17 G06真实WebEngine上传整链探针：保持仓库源码冻结，在D:/ZQ-Acceptance/probe_native_upload_webengine.py独立运行；真实QWebEnginePage + BrowserObserver + NativeTaskUpload + QThread准备 + SQLite授权 + 固定上传脚本验证一次change、内容一致、隔离世界不可从主世界读取、许可单次消费、再次请求拒绝；exit0。证据根D:/ZQ-Acceptance/native-upload-real-783734acceae4731abf77a803729d529。页面为setHtml合成同源页面，不向外部上传，也不代表实际OA业务成功。完整租约/主入口/真实网站整体验收仍待完成。

- OA只读环境核查：2026-09-17使用用户已授权测试账号登录https://zhongqinoa01.com，正常进入/workbench；发现ZQ-202605-007“实验项目”（报告送审）与ZQ-202605-006“实验项目”（已归档）。已就007合成附件上传且不推动流程发起精确确认，尚未上传/修改/保存密码。登录是在Codex浏览器中核查，不是本产品EXE浏览器验收。

- 当前活动诊断回归：exec session56792，798平台测试，逐项-v/--durations=30/-o faulthandler_timeout=90；临时目录D:/ZQ-Acceptance/platform-duration-diagnostic，JUnit目标D:/ZQ-Acceptance/platform-duration-diagnostic.xml。下一轮先轮询该句柄；源码暂冻结，不能重启或声称通过。该诊断不替代完整三套验收脚本。

- 2026-09-17 G06主窗口上传接线：新增当前会话登记成果后台发现/完整性核验与原生选择窗口，默认不选、不扫描任意磁盘、不向模型发路径；选择后快照冻结候选并注入运行工厂，实际上传继续单独确认网站/业务对象/版本。取消或上下文变化等待发现线程退出，不启动浏览器任务。修复计划确认缺失upload/download映射的KeyError及错误“不上传”文案。19来源邻近、11入口/候选/选择/确认联合、1字体及换行截图复验通过；限定8文件Ruff及4文件Mypy通过（随后只增测试字体和列表换行）。证据upload-candidates-green、upload-entry-verified、upload-selection-render（D:/ZQ-Acceptance）；截图已查看。尚缺真实Qt上传整链、持久防重复/业务回执及真实OA验收，不能声称已产品验收。无付费调用/真实上传/发布部署。

- 前次完整回归session65045已终止，exit124：客户端217、服务端183通过；平台791项运行至约九成触发脚本600秒时限，无最终JUnit，不算通过。目录末端定位test_step_delivery；独立6项22.59秒通过，最慢4.70秒，证据timeout-step-delivery；未复现该处卡死。暂不改变600秒验收门槛或宣称根因已证实；下一次平台诊断使用逐项输出/耗时及90秒栈转储定位累计耗时，完整回归通过基线仍1170。

- 活动完整回归：D:/ZQ-Acceptance/r-643ce6bca36c4a7a93fc5b2f9e24e141，exec session 65045。客户端217通过，服务端183通过（Starlette依赖弃用警告1条），平台测试仍运行，尚无最终结果。继续时先轮询此句柄，测试结束前不得改源码或重复启动全量；不得将本次回归记为完成。

- 2026-09-17 G06上传确认及生命周期收尾：原生确认窗口默认取消，必须勾选网站/业务对象/文件版本同意项，40秒或上下文失效自动拒绝，网页与模型文本按纯文本显示；截图已人工查看，尚未接入主窗口入口。适配器在提交授权前锁定SHA，当前运行内已尝试成果移出模型候选，未知状态不自动重复提交（尚无跨重启持久防重复）。新增线程启动失败红灯复现：worker从未启动却永久等待finished；修复仅释放未运行worker，已运行worker继续等待实际结束。8项确认窗口/上传适配器/执行循环测试通过，D:/ZQ-Acceptance/upload-lifecycle-green；红灯upload-start-red；界面截图upload-prompt-check/test_upload_prompt_requires_ex0/upload-confirmation.png。限定4文件Ruff及2文件Mypy通过。最新完整回归仍1170，正在启动新完整回归；主窗口候选/确认接线、真实Qt上传整链和网站业务回执仍待完成。API0元、无OA上传、无发布部署；目标active。

- 2026-09-17 G06上传执行循环/工厂连接：BrowserExecutionLoop注入uploads，将仅元数据候选发送模型、upload提案转原生request、成功派发后重新观察；终态等待上传实际worker退出，迟到回调不启动下一步。NativeTaskUpload新增候选ID→本地来源引用、原生confirm_upload调用、确认前后观察检查及准备结果name/size/sha256与确认候选一致性校验。工厂注入可选候选/确认器、file观察权限和清理。先loop1红灯、原生request5红灯、工厂1红灯；最终11执行循环/适配器邻近+5真实Qt工厂测试通过，限定Ruff及3文件Mypy通过。证据D:/ZQ-Acceptance/upload-loop-verified及upload-factory-green；无活动测试句柄。最新完整回归仍1170，最近增量尚未全量。尚缺主窗口本轮成果候选构建/确认UI、真实Qt文件整链、上传业务回执持久核对；需补已派发候选防重复和未知状态恢复后不得重放。当前执行层接通不代表产品上传可用。下一轮完成主窗口候选与UI接线后全量。API0元，无真实OA写入/EXE/GitHub推送/云端部署，目标active。

- 2026-09-17 G06上传共享协议：BrowserIntent/BrowserStepProposal增加upload；BrowserStepRequest增加最多32条仅id/name/size/sha256的UploadArtifact候选，禁止路径/二进制/重复ID/范围外清单；提案必须是清单成果、当前启用file控件和明确object_label，其他动作不得夹带上传字段。空新字段序列化省略保持旧形状。服务端browser_upload能力及下一步提示词已实现，客户端必须显式能力、不能用旧OpenAPI猜支持。修前2协议红灯；37服务端协议/OpenAPI/模型请求关联、14客户端门禁、19平台scope/执行循环邻近通过，证据upload-protocol-verified/upload-capability-green/upload-protocol-neighbors（D:/ZQ-Acceptance）。两共享契约Mypy通过；限定契约/新测试Ruff通过；扩大Ruff到既有api及remote_auth发现47项既有Depends/异常处理规则告警，本轮不宣称这些文件全静态通过，不以修改既有无关逻辑消除。最新全量1170，新上传几轮尚未全量。尚未向BrowserExecutionLoop传入候选、上传执行/UI/工厂未接，当前运行时不具完整上传能力；下一轮接这些入口并真实Qt整链及全量回归。未部署新服务能力，无真实费用/上传/EXE/推送，目标active。

- 2026-09-17 G06原生上传任务适配器：新增browser_native_upload.NativeTaskUpload，连接真实后台准备及SQLite动作授权、UploadTransfer分块传输；活任务/来源URL/页面epoch/nonce复核，取消先阻止派发并等待实际worker.finished后回调，不销毁运行中线程。BrowserObserver新增显式can_upload，只有该范围可观察file控件，reserve_upload单次消费原生观察、不授予文件权限。先观察1红灯、适配器4红灯；首次正向测试3秒未等到后台结果，改15秒等待并保留实际状态诊断，未放宽业务断言；最终24关联通过，含校验完成时撤销真实持久授权导致零commit、拒绝/页面变化/取消，限定Ruff及2文件Mypy通过。证据D:/ZQ-Acceptance/native-upload-verified；本轮适配器页面为合成fake，固定脚本另有真实WebEngine测试，尚非真实整链页面/OA上传。最新全量1170，最近两轮新增尚未跑全量。下一步工厂/执行循环/原生确认UI与模型协议及能力门禁接线，补真实Qt整链和运行中关闭测试；阶段闭环再全量。无付费调用/实际OA写入/EXE/推送/部署，目标active。

- 2026-09-17 G06上传派发连接增量：真实WebEngine红灯复现异步digest完成直接触发change，没有原生最终授权复核时点。browser_upload_script改为finish只到verified，新增commit才触发input/change；校验后abort再commit不会派发。新增browser_upload_transfer.UploadTransfer，固定分块操作、每调用/回调活状态检查、60秒时限、最终commit门禁、序号阻断重复回调、关闭清空payload并abort；仅原生组件，不向模型开放。新控制器先1红灯，最终17脚本/控制器/worker/持久授权关联通过，限定Ruff和2文件Mypy通过；证据D:/ZQ-Acceptance/upload-transfer-verified。最新全量仍1170，本轮新增未跑全量；尚未接NativeTaskUpload/Observer单次文件观察、worker生命周期、工厂/循环/UI/共享协议/能力，不是实际网站上传。下一轮将这些组件连成任务适配器并补真实Qt整链及拒绝/超时/页面变化测试，阶段闭环后跑全量。无实际上传、费用、EXE、GitHub推送或部署，目标active。

- 2026-09-17 后台上传准备轮完整回归收尾：session83065退出0，215客户端+174服务端+781平台=1170 passed，runner ok；证据D:/ZQ-Acceptance/r-85a213f221804a1fb081ecbe52ec2ef7。限定Ruff及2文件Mypy通过。服务端有1项Starlette/httpx弃用警告，无测试失败。当前无运行中的回归句柄。下一轮：原生上传适配器连接后台worker/一次许可/页面epoch与标签lease/固定分块脚本，保证取消等待线程退出、迟到回调不派发；再接UI/协议/能力及网站回执。特别注意固定脚本异步digest期间仍需在最终派发前取得活授权复核，不能仅凭调用finish时的检查。尚未接实际网页上传、未做真实OA/模型验收，费用0元，无EXE/GitHub/云端发布，目标active。

- 2026-09-17 恢复核对：固定上传脚本轮session57410已退出0；读取三个JUnit报告核实215客户端+174服务端+776平台=1165通过，零失败/错误/跳过，证据D:/ZQ-Acceptance/r-8cd4cc766ce245e7bed40b58b77e35be。不要再轮询或重跑该句柄。

- 2026-09-17 G06后台上传准备：新增browser_upload_worker.UploadPreparationWorker，先确认再后台准备隔离副本，分块读取、句柄/路径身份与大小/SHA256复核，然后申请既有持久许可，返回不可变bytes；不调用Qt页面，不向网页/模型传路径。2修前红灯、45上传链路专项通过；类型修正后18来源/worker复验通过，再补准备期间取消无授权3项worker通过。来源解析新增64MiB读取前限制及记录大小/实际大小一致校验，2修前红灯，未降低既有边界。限定Mypy通过；完整回归尚待本轮执行，最新全量为1165。不代表浏览器上传可用：原生适配器、逐步页面/lease检查、确认UI/模型协议/服务端能力、实际业务回执未接。累计真实API费用0元，无EXE/推送/部署。下一步接原生上传执行与线程生命周期。

- 2026-09-17 G06固定上传数据通道：新增browser_upload_script，固定begin/chunk/finish/status/abort操作，不收代码或本地路径；仅隔离ApplicationWorld使用。显式include_files观察可列出单文件控件，默认关闭，Control增加file但模型upload动作未开放。沿用nonce/DOM引用/字段快照，主frame、HTTPS同源、表单同源POST/非新窗口、可见命中、禁用/已有文件、总量64MiB和64KiB分块/offset检查；整份SHA256与长度一致、页面仍有效才设置File并触发input/change；操作状态不视为网站业务成功。真实WebEngine测试正常分块、一次性、DOM变化、摘要错误、取消、错offset、禁用及跨站表单，元数据/超限/任意操作负测。先1红灯；首轮9邻近失败定位为默认脚本多参数破坏旧fake解析，保持默认单参数、仅显式文件观察加参数，未弱化测试。最终18专项/邻近通过，限定Ruff和3文件Mypy通过。完整回归已启动，handle/目录以紧随工具输出记录为准。仍需原生适配器逐步live授权/页面复核、数据读取worker、确认UI/模型协议/服务端能力及实际上传回执；当前未开放实际上传，隐藏控件/多文件/目录上传尚未支持。无API费用/EXE/推送/部署，目标active。

- 2026-09-17 持久上传授权轮完整回归：原session 50083退出0，215客户端+174服务端+768平台=1157 passed，runner ok；证据D:/ZQ-Acceptance/r-748c6345b3374813861a1dbfe51a3f56，未重复启动。页面接入调研发现Qt chooseFiles只提供mode/oldFiles/acceptedMimeTypes，不提供来源frame/具体DOM控件（官方https://doc.qt.io/qt-6/qwebenginepage.html#chooseFiles），因此不将该回调误当已验证的目标控件。新增仓库外真实WebEngine可行性探针D:/ZQ-Acceptance/upload-api-probe.py，隔离ApplicationWorld用DataTransfer/File向主页面指定input交付3字节合成数据，MainWorld change事件读到正确内容，隔离world不读MainWorld结果；退出0，无实际网络上传。下一步用固定受控脚本实现nonce/DOM/页面/授权校验及有界数据传递，原生路径不进页面，chooseFiles继续默认拒绝；最终网站回执另外核对。本轮探针不是生产上传实现、不是TLS或OA联调，未开放模型upload能力。无费用/EXE/推送/部署，整体目标active。

- 持久上传授权轮全量运行句柄：exec session_id=50083；证据D:/ZQ-Acceptance/r-748c6345b3374813861a1dbfe51a3f56。恢复时先轮询此handle，未终态不重复启动。

- 2026-09-17 G06持久上传授权连接层：新browser_upload_authorization.UploadAuthorization在磁盘验证阶段复核当前会话成功成果来源及隔离副本，把对象/来源引用/副本摘要绑定到现有BrowserActionRequest/数据库动作回执，再发放原生一次许可；消费前复核副本文件身份，再原子消费数据库回执。仅原生BrowserTaskScope与BrowserActionRequest增加独立upload动作，普通click范围不能授权上传。模型BrowserIntent/BrowserStepProposal未开放upload，BrowserPage.chooseFiles仍拒绝，未连接运行时/UI；旧端不会被当作已有上传能力。5修前红灯，26连接层/任务scope/既有动作回执关联通过，限定Ruff/Mypy通过。完整回归已启动（本轮工具输出记录artifact目录/handle）；未获终态前不算通过。源文件及业务模板未改，无网络文件上传、扣费、EXE/推送/部署。下一轮接原生字段/页面验证与确认流程，并完成上传协议及能力门禁，不能以此模块独立代表上传可用。

- 上述原生上传许可联合复验已完成：session 23981退出0，39 passed in 11.40s，证据D:/ZQ-Acceptance/upload-permissions-verified；无需重复轮询或重跑。原生适配器/持久授权/UI/模型协议接线仍待实施。

- 2026-09-17 G06原生一次性上传许可：新增browser_upload_permissions.UploadScope/UploadPermissions，绑定完整任务身份、revision/claim、环境、tab/page_version、精确HTTPS origin、明确业务对象、字段ID、持久回执ID及完整暂存文件fingerprint；仅原生confirmed=True发放，60秒到期、单次消费（不匹配尝试也消费）、任务/标签撤销与关闭清空，最多128待用许可。11修前红灯，22新许可+既有登录许可专项通过，限定Ruff/Mypy通过；上传来源/准备联合测试进行中，D:/ZQ-Acceptance/upload-permissions-verified，session 23981。此服务尚未接持久授权/原生页面，不独立证明回执有效，也不开放上传；下一轮必须连接原生适配器与实际目标选择，不能仅凭该scope执行。新增模块未跑完整回归，最新全量仍1141。API0元、无EXE/推送/部署，目标active。

- 2026-09-17 上传来源/隔离准备完整回归收尾：继续轮询原session 30199，已退出0，215客户端+174服务端+752平台=1141 passed，runner ok；证据D:/ZQ-Acceptance/r-92869dc4687849cca70355dc25047042。未重启重复测试。上传授权/页面接线、暂存清理与实际网站验证仍未完成；下一轮一次性上传许可绑定。API0元，无EXE/推送/部署，目标active。

- 2026-09-17 G06上传隔离准备：新增browser_upload_preparation.prepare_upload，先验证来源，再在项目非系统盘browser_uploads唯一目录分块复制；源句柄身份前后复核、副本SHA256核验、复制后再核对来源任务/版本，最后同卷无覆盖发布。返回仅供原生授权流程的副本，不授予网站上传权限；失败暂存隔离保留、不递归删除，冷恢复/清理尚待实现。修前2红灯；最终17来源/准备专项通过（含真实本地生成适配器的组合步骤正向及预检步骤拒绝、复制后来源变化拒绝），限定Ruff及2文件Mypy通过。完整回归已启动，证据D:/ZQ-Acceptance/r-92869dc4687849cca70355dc25047042，exec session_id=30199；当前尚无终态，恢复时先轮询该handle，不重复启动。最新已完成全量仍1124。目标网站/对象/一次性许可、原生chooseFiles入口、真实上传业务回执仍待接，不宣称上传可用；BrowserPage仍拒绝上传。无实际OA写入、扣费、EXE/推送/部署，整体目标active。

- 2026-09-17 G06上传来源地基：检查确认BrowserPage.chooseFiles仍统一拒绝，未开放任意文件选择。新增browser_upload_source.UploadSource（任务/类型/序号/版本及可选步骤引用，不收路径）和原生resolve_upload_source，要求当前会话成功任务、已校验生成成果或有delivery_versions的审核副本；复用组合步骤记录读取，非系统盘文件身份/分块摘要核验，支持取消。先9红灯；发现add_file复制附件，仅路径比较不足，增加摘要检查阻止原件改名/复制外发。最终13新来源测试+9下载完整性邻近=22 passed，证据D:/ZQ-Acceptance/upload-source-verified；限定Ruff/Mypy通过。本轮未接执行入口、未跑新增代码的完整回归；最新全量仍1124。组合成果解析代码已写但专项正向用例尚待补，不宣称上传可用。下一轮绑定网站/业务对象/一次性动作许可，准备隔离副本、原生文件选择及提交回执；BrowserPage当前继续安全拒绝上传。无OA写入、付费调用、EXE/推送/部署，整体目标active。

- 2026-09-17 G06浏览器结果恢复文案修复：5个失败用例复现choose_session→show_result把浏览器历史结果当预检。提取show_browser_result供实时completed和历史show_result共同使用，依据真实run.state及verified组合决定成功/取消/待补充/未验证，保留只读人工确认与不可信网页依据标识，使用已有按任务append_output去重，不删除历史消息。5修前失败、13专项/下载入口/主窗口邻近通过，限定Ruff通过。完整回归215客户端+174服务端+735平台=1124 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-8a2c0ae9c78e4d7dac04808d8fb7e089。下一步下载文件安全打开/后台复核及上传链路；真实网站、OA目标项目、签名更新和三端发布仍未验收。API累计0元，无EXE/推送/部署，G06及完整目标active。

- 2026-09-17 G06下载成果对话入口：先红灯复现重启/取消任务后对话没有下载记录，新增browser_download_delivery，主窗口从持久回执显示文件名、字节及“下载时完整性已校验；业务内容待核验”。提供打开所在文件夹入口，不直接执行或打开下载文件、不在GUI线程哈希；点击检查当前会话、回执、目录和文件身份，拒绝附加查询/碎片及失效链接。17专项/邻近通过，追加原生窗口截图测试2项通过，限定Ruff/Mypy通过；中文截图D:/ZQ-Acceptance/download-delivery-visual/test_download_visible_after_ta0/download-conversation.png已检查。ui-ux-pro-max仅用于清晰状态与原有对话布局，不采用营销页设计。完整回归215客户端+174服务端+730平台=1119 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-9f52f6c3d68a461caeadaf5646c8180d。截图发现会话恢复show_result把browser结果误标资料预检，已定位app.py但本轮未改，下一轮先补失败测试修复。直接打开下载文件的后台复核、真实TLS下载/上传及业务回执仍待验收。无EXE/推送/部署，API累计0元，G06和整体目标active。

- 2026-09-17 G06下载完整性与持久回执：新增磁盘后台分块SHA256及读取前后文件身份核验，取消每块检查；界面线程只接收结果并复核任务/页面/授权后登记。schema 8新增下载成果表，绑定已消费的动作许可、任务及步骤，拒绝换目录/来源/许可、撤权及跨会话解析；重复登记幂等，历史读取校验载荷摘要。新增v7迁移备份/故障回滚及Qt校验期间取消生命周期测试，取消后不登记成果、不继续调用模型。11专项通过，限定Ruff及4文件Mypy通过。完整回归215客户端+174服务端+728平台=1117 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-bef6dc46b7d8407799818bf6389c1d43。尚未接对话成果入口，实际TLS网站下载、上传及业务回执未验收，不代表G06完成。API累计0元；无本轮EXE/推送/部署，整体目标active。

- 2026-09-17 G06 Agent直接链接下载接线：共享scope/动作增加download，只允许当前观察link编号，不收模型URL/路径；固定隔离脚本在nonce/DOM/字段/可见性复核后解析同站HTTPS链接，不点击、不提交，跨站及重复观察拒绝。BrowserObserver独立download门禁，NativeTaskDownload接现有单次任务许可、保存目录授权摘要与真实文件大小核对，取消/页面变化/来源URL不符不继续。工厂与主窗口传入同一BrowserSession下载控制器，循环等待实际交付后再观察，completed_downloads只传名称/字节数/来源，不传本地路径；旧请求无该字段，browser_download显式能力门禁阻止旧端。服务端提示词明确已保存不等于业务正确，避免重复下载。修前协议/脚本/适配器缺项红灯；32协议/循环/窗口关联、23工厂/适配器/门禁关联、限定Ruff和10文件Mypy通过。完整回归215客户端+174服务端+718平台=1107 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-46a64aba7dfd41658084d8a9135b12da。真实WebEngine验证了固定脚本目标解析，适配器为合成page+真实下载控制器，尚无实际TLS网站Agent整链下载。当前本地回执仅运行时保存，文件哈希/持久回执/对话成果入口、按钮生成下载/上传及业务核验仍未完成。下一轮优先后台文件完整性核验及持久成果入口（避免GUI线程哈希大文件）。API累计0元，无EXE/推送/部署，G06及目标active。

- 2026-09-17 G06任务下载入口：先复现任务页无任务许可仍弹保存框/接受下载，新增Native-only TaskDownloadPermission，绑定当前导航租约task_id与page对象、单次领取、来源URL/目标路径准入回调；任务页无许可拒绝，旧许可不能复用或冒用另一任务。保存框前后、进度及正式publish前检查有效性；100ms Qt计时器覆盖无网络进度时的取消，撤权/换owner/取消保留隔离暂存、不交付。补红灯修复手动保存框期间页面被任务接管的竞态。31专项/邻近（含真实本机HTTP下载）及新增定时器验证通过，限定Ruff/Mypy通过。完整回归213客户端+168服务端+712平台=1093 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-b9c4717270f04f3387a8f0b80dffc7ca。当前仅控制器任务许可和取消边界，尚无模型download提案/原生下载适配器/对话成果回执，不是Agent下载端到端验收；普通手动下载不变。下一步接通模型动作、固定脚本的下载目标解析、native适配器、下载完成独立回执及成果登记。API累计0元，未EXE/推送/部署，G06与整体目标active。

- 2026-09-17 G06可信登录接线：browser_runtime_factory按当前BrowserSession账号/环境创建本地CredentialVault与NativeTaskLogin，失败/终态关闭；browser_window接原生账号选择（仅已获Agent许可、默认未选、默认取消、任务/页面失效关闭，40秒时限）。服务端新增browser_saved_login能力及无凭据login提示词，客户端新范围禁止旧OpenAPI路径降级猜测支持。先红灯证实缺门禁/UI/工厂；一次误用C盘pytest临时目录被既有业务存储规则拒绝，已在D盘重验，未放宽规则。22首轮、6窗口/真实WebEngine与DPAPI既有链路、10客户端协议测试通过，限定Ruff与4文件Mypy通过。中文截图D:/ZQ-Acceptance/login-window-green/test_account_prompt_requires_c0/login-prompt.png已看（初次offscreen缺中文字体，测试显式加载字体后复验）。完整回归213客户端+168服务端+700平台=1081 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-3a42498f54ad4d82ad5fa69895cc6454。本轮真实DOM/DPAPI为既有可信填充测试，新工厂验证装配/生命周期，尚未进行实际站点Agent整链登录/TLS验证，不能声称G06验收。下一步通用下载/上传任务绑定和独立业务回执，再做真实站点验证；OA目标项目仍待指定。API累计0元，无EXE/推送/部署，目标active。

- 2026-09-17 G06可信登录动作协议与执行循环：先写测试复现协议拒绝login及循环缺少原生适配器入口，再增加无账号/密码/凭据ID参数的login提案（必须已有观察并在scope内）。循环可注入NativeTaskLogin，页面变更拒绝、未装配时needs_input、取消关闭适配器、迟到回调不重放；填充后重新观察，不视为登录成功。27协议+11执行链关联通过，限定Ruff和两文件Mypy通过。完整回归210客户端+167服务端+699平台=1076 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-47ec0cabe3804b5287b771a1b68c1cf5。工厂/原生账号选择UI、服务端能力标志及旧服务端门禁尚未接，模型提示词尚未开放该动作；不是实际站点登录验收。下一步完成这些接线及真实Qt/DPAPI验证。API累计0元，无EXE/推送/部署，G06及整体目标active。

- 可信登录连接层轮完整回归通过：210客户端+161服务端+698平台=1069 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-42671ae5486140fabcf17c104c4d5a71。18专项/邻近、限定Ruff及两文件Mypy通过；核验SQLite异常安全拒绝已验证。新适配器测试复用真实SQLite授权表与既有TrustedLogin，页面/凭据为合成fixture；未连接模型动作及UI，不是实际登录验收。下一轮协议、执行循环、工厂和原生账号选择一起接通；仍需真实Qt/DPAPI及网站验证。API0元，无EXE/推送/部署，G06及目标active。

- 2026-09-17 G06可信登录连接层：先复现核验active回调SQLite异常逃逸，补sqlite3.Error安全拒绝；新增browser_native_login.NativeTaskLogin，连接当前原生任务/页面、已获Agent许可账号、本地选择回调、持久单次动作摘要回执、BrowserTaskPermissions和TrustedLogin。确认前后复核账号许可和页面，拒绝/取消/撤权/未知账号不解密；仅返回填充状态、不提交登录，不向模型返回账号密码。测试第一次失败为误假设动作表有action列，已按实际binding_sha256/consumed表校验，不改表。18连接层/既有登录/核验关联通过，限定Ruff及两文件Mypy通过。全量进行中D:/ZQ-Acceptance/r-42671ae5486140fabcf17c104c4d5a71。当前是适配器边界，模型登录动作协议/执行循环/工厂/本地账号选择UI尚未接，不能称客户端Agent登录可用。下一轮完成这些接线及真实Qt/DPAPI链路。API0元，无EXE/推送/部署。

- 只读结果用户核验轮完整回归通过：210客户端+161服务端+693平台=1064 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-42d45817258b4cf88bca4978d28eeb37。8策略/UI/持久回执/宿主/窗口关联及限定Ruff/Mypy通过，中文截图已看。这仅完成只读范围的人工核验闭环，不是写入回执或自动业务验证；点击/填写/账号使用范围仍拒绝走此捷径。下一轮可信登录/业务回执执行链；还需覆盖核验弹窗中的数据库失效异常以保证原生回调安全关闭。OA测试项目名称/编号待用户补充，其他工作可继续。API0元，无EXE/推送/部署，G06及目标active。

- 2026-09-17 G06只读结果人工核验闭环：新增browser_completion，严格限制observe/navigate/scroll/wait范围；确认前后均本机重读证据，任务/账号/授权/页面失效拒绝。原生对话框默认不确认、主动勾选、纯文本目标/结果/引用、上下文变化自动关闭；接browser_window。BrowserTaskHost校验并持久user_confirmed_readonly回执（任务、目标/结果/证据哈希、来源、时点），对话明确“已由你核对确认”，不冒充自动验证或网站写入回执。8策略/原生UI/持久回执/宿主/主窗口关联通过，三文件Mypy与限定Ruff通过；中文截图D:/ZQ-Acceptance/completion-ui-green/test_completion_dialog_is_expl0/completion.png已检查。ui-ux-pro-max只影响留白、默认取消/禁用及可访问控件，未采用网页营销结构。全量进行中D:/ZQ-Acceptance/r-42d45817258b4cf88bca4978d28eeb37。写操作回执及可信登录/下载/上传仍须继续，不代表G06/OA通过。再次单项询问OA允许写入的项目名称/编号；账号和合成上传许可已具备，不向任意项目上传。API0元、无EXE/推送/部署。

- 完成证据时效轮完整回归通过：210客户端+161服务端+690平台=1061 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-a2ad00d4349747ba889f5791354e1929。15邻近及限定静态通过，新Qt用例含正常/消失/两阶段导航/取消/撤权/超时七情形。下一轮需接通业务结果核验（确认目标与交付、业务回执、任务身份及持久结论），不是继续把证据引用当业务成功。G06与目标active，API0元，无EXE/推送/部署。

- 2026-09-17 G06完成证据时效：红灯复现finish直接沿用模型调用前旧观察。BrowserExecutionLoop新增原生重观察，先确认原观察仍属于当前页，再校验重读origin/page_version及证据原文；取消、前后导航、证据消失、权限失效或10秒读取超时不采纳结论。证据哈希仅运行时保留，未新增完整网页持久存储或模型请求；通过后仍为needs_verification，绝非业务成功。15执行循环/宿主/工厂/主窗口关联通过，限定Ruff/Mypy通过；全量进行中D:/ZQ-Acceptance/r-a2ad00d4349747ba889f5791354e1929。业务目标/回执独立验证器和UI还须接通，不能据此宣布OA验收。API0元，未EXE/推送/部署。

- 滚动/等待工具轮完整回归通过：210客户端+161服务端+689平台=1060 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-04f05b71949a4e6b8c3ef366c798bd2c。真实WebEngine脚本滚动位置、一次观察消费、Qt等待与取消/导航、旧服务端拒绝新动作已验证；限定Ruff和运行时5文件+remote_auth_service Mypy通过。当前仅主文档视口；业务完成独立核验、可信登录/下载/上传执行链及真实OA仍未验收。下一轮优先业务核验，不以动作派发或模型finish作为成功。API0元，未EXE/推送/部署，G06及整体目标active。

- 2026-09-17 G06滚动/等待工具：红灯复现协议及observer缺能力、旧服务端仍收到新动作。共享协议新增scope scroll/wait，scroll只允许up/down，wait为100–5000毫秒且必须已有观察；执行循环用Qt定时器，取消/导航失效不继续，动作后重新观察。主页面滚动使用固定隔离脚本，复核观察nonce/DOM状态/字段值，原生确认与单次授权回执沿用现有门禁；不支持任意脚本。服务端新增browser_view_actions能力标志，客户端新动作必须显式能力预检，禁止仅凭旧OpenAPI同路径猜测支持。29协议/观察及12真实Qt/客户端关联通过，限定Ruff和5文件Mypy通过。完整回归进行中D:/ZQ-Acceptance/r-04f05b71949a4e6b8c3ef366c798bd2c。当前仅主页面视口，不覆盖内嵌滚动区；真实业务完成核验、Agent登录/下载/上传及OA验收仍待做，API0元，无EXE/推送/部署。

- 多轮浏览器目标传递轮完整回归通过：208客户端+153服务端+687平台=1048 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-61a51b7a25674c26901a2144dc5208f1。新增3项目标/超限/旧快照测试及真实主窗口模型入参断言；三文件Mypy、限定Ruff通过。确认server browser_step直接序列化目标字段，无需本轮协议/计费改动。下一步补业务完成独立核验及通用浏览器工具缺项，真实OA/非OA和模型尚未验；未EXE/推送/部署，API累计0元，G06及目标active。

- 2026-09-17 G06多轮执行目标：红灯复现快照无完整browser_goal及超长上下文未拒绝。build_understood_browser_task保存相关user/assistant消息、当前输入、目标、限制、交付要求和非授权声明；不包含附件正文。原生工厂传递该目标，范围确认展示同一文本；有理解但缺完整目标的旧快照拒绝降级成末句输入，超过12000字符拒绝且不截断。初轮24关联通过，补真实窗口模型入参断言及旧快照负测；三文件Mypy与限定Ruff通过。待完整回归；真实语义/网站业务核验仍未验，无API费用、打包、推送或部署。

- 浏览器执行追问续接轮完整回归通过：208客户端+153服务端+684平台=1045 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-2700af3c4eb343e59eacb883276e7b59。本轮新增5项状态测试，并扩充真实主窗口测试验证简短回答携带原始请求和问题、不会自动新建执行任务。全量后仅Ruff调整测试导入格式，14项状态测试复验通过。下一步传递完整多轮目标/限制，然后补浏览器业务独立核验与工具缺项；G06及整体目标仍active，无EXE/推送/部署，API累计0元。

- 2026-09-17 G06执行追问续接：先复现ConversationState缺少执行交接及真实主窗口显示追问但question为空；新增execution_question，绑定原理解task/revision、仅已关闭理解允许交接，生成新理解身份并清空事实授权。browser_window把原请求和理解版本写入授权快照；BrowserTaskHost在终态同一事务验证下一轮上下文大小并持久待答问题。旧任务/重复结果不覆盖新任务，事务失败整体回滚，不继承浏览器动作回执。目标16项及三文件Mypy/Ruff通过，新增3项边界负测后全量进行中：D:/ZQ-Acceptance/r-2700af3c4eb343e59eacb883276e7b59。尚须完整回归确认；多轮理解目标/限制传给浏览器执行、业务独立核验及工具缺项继续待做。仅模拟模型/Qt测试，无真实网站操作、API0元，无EXE/推送/部署。

- 主窗口浏览器入口轮完整回归通过：208客户端+153服务端+679平台=1040 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-224509650179483c830a448979d32900。17窗口关联、5客户端接口测试及新文件限定Ruff/Mypy通过。主窗口已接浏览器意图、范围确认、专属页、原生提示与运行时；真实模型/站点业务未验。下一步浏览器执行中追问的ConversationState续接及理解目标/限制传递，再补业务完成独立核验与工具缺项。未EXE/推送/部署、API0元，G06与总目标active。

- 2026-09-17 G06主窗口浏览器入口：三项入口红灯后app.submit向具备本地浏览器方法的客户端开放原生能力，routing_finished单独处理browser并在后台会话只提示返回确认。新增browser_window，复核owner/project/session/model/理解revision，确认范围后创建专属页、持久任务授权及BrowserTaskHost，接现有范围框、BrowserActionPrompt和真实运行时；取消/模型改变/会话改变不执行。服务端兼容缺能力红灯后RemoteSessionClient理解前只读检查browser_step，旧服务端不发送不支持的浏览器adapter，原文件目录保留，按实际发送目录复验响应。
  17窗口/工厂/组合计划/确认关联及5客户端接口测试通过，新增文件限定Ruff/Mypy通过。全量进行中D:/ZQ-Acceptance/r-224509650179483c830a448979d32900。测试为真实Qt窗口/WebEngine+模拟模型，仅验证消息→理解→确认→专属页→提问结果；未导航真实站点或付费调用。浏览器执行中追问尚需连接ConversationState续接，完成建议仍默认待核验而非自动成功；这些是下一轮施工项，不能宣称整个G06或业务端到端完成。未打包推送部署，API0元，目标active。

- 浏览器确认UI轮完整回归通过：206客户端+153服务端+675平台=1034 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-01daec5efea74171b9373345666c9569。21专项/邻近、限定Ruff/Mypy及中文截图检查通过。下一步app.py浏览器意图分支与原生确认/运行时接线，需同时保证旧服务端能力不足不损坏原文件任务。自然语言入口仍未开启；G06/目标active、API0元，未打包推送部署。

- 2026-09-17 G06浏览器确认界面：按agent-tdd-fix先复现任务确认未显示网站/动作范围；plan_confirmation新增browser_task专用纯文本范围（网站、动作、环境、模型、有限观察外发、不上传文件），主动勾选才可确认且默认取消；文件计划原语义保留。BrowserActionPrompt新增navigate，确认前校验精确origin和完整URL摘要，不接受替换地址，继续使用过期/撤权关闭机制。UI技能只用于间距、焦点、可访问名称及禁用状态，未套用营销布局或替换原UI。
  21专项/邻近通过；限定Ruff/Mypy通过（import格式自动修正）。已查看D:/ZQ-Acceptance/browser-confirm-green/test_browser_scope_and_navigat0/scope.png与navigation.png中文截图。全量进行中D:/ZQ-Acceptance/r-01daec5efea74171b9373345666c9569。主窗口自然语言入口仍未启用，实际网站/付费模型未验。API0元，无EXE/推送/部署，G06与目标active。

- 浏览器运行时工厂轮完整回归通过：206客户端+153服务端+674平台=1033 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-cbfea84e967d416dbe89738cb4016831。最终5真实WebEngine组装场景及限定Ruff/Mypy通过；初轮13相邻通过。下一步主窗口browser意图分支、范围确认及导航确认UI；当前真实页面仅空白页、模型回复合成，外部网站业务未验。G06及目标active，API0元，未打包推送部署。

- 2026-09-17 G06实际运行时组装：缺模块红灯后新增browser_runtime_factory，将已认领BrowserTaskHost、现有BrowserTaskLeases/BrowserObserver/BrowserNavigation/BrowserActionGate与BrowserExecutionLoop连接；授权从宿主数据库读取，校验owner/project/session/task、step claim及test/production环境，每步重查授权。导航先由可信回调确认具体URL，持久单次回执先消费再导航；同步跳转门禁不弹窗，限制在已授权HTTPS站点。结束释放标签与观察器，但保留导航限制直到用户主动接管，防迟到跳转放权。
  真实WebEngine空白页+模拟模型测试覆盖正常澄清、拒绝导航、跨站/HTTP拒绝、确认期间取消/撤权、未确认与环境错配；13相邻通过后增撤权场景，最终5工厂场景通过，限定Ruff/Mypy通过。全量进行中D:/ZQ-Acceptance/r-cbfea84e967d416dbe89738cb4016831。尚未接主窗口自然语言入口/实际确认UI；测试未真正导航外部站点或做业务提交，不能称OA/真实模型通过。API0元，无EXE/推送/部署，目标active。

- 下载来源测试修正轮验收：15次独立进程真实网页点击下载全部通过（D:/ZQ-Acceptance/download-probe-a76eacfadf894cfaa675015ed9d9bf9c，0.xml至14.xml），19邻近下载门禁/交付用例及限定Ruff通过。完整回归D:/ZQ-Acceptance/r-1f60b5797967489ca43fde5692172472：206客户端+153服务端+669平台=1028 passed，runner退出0/ok。确认此前失败为测试直接下载API无来源页面被正确拒绝，不改生产下载权限。继续G06实际浏览器工厂和自然语言入口；未打包推送部署、API0元，目标active。该证据覆盖本机合成站点，不替代OA/非OA真实站点及干净Windows验收。

- 2026-09-17 下载偶发失败定位与最小调整：
  - 现象：首次下载在弹出保存路径前已取消，原全量1失败；不是输出权限或模型摘要断言失败。
  - 故障层：测试驱动/Qt下载来源兼容。无窗口模式独立复测并非每次复现；逐进程压力探针第11次失败。
  - 证据：D:/ZQ-Acceptance/download-probe-5816ace6d405448b88408f4fcda4deca/10.xml，has_page=False、owned_page=False、save_page=False、controller_closed=False。生产门禁正确拒绝无来源页面。Qt官方https://doc.qt.io/qt-6/qwebenginedownloadrequest.html#page明确非页面内容发起的下载可能返回空page；原测试在about:blank初始化时直接page.download，错误假定总有来源page。
  - 最小修改：测试HTTP服务增加真实链接页，等待/index加载后向WebEngine focusProxy发送鼠标点击；不放宽生产门禁、不增加超时、不重试已发出的下载。首次mouseClick发送到外层view未进入网页，随后按既有浏览器点击测试惯例修正到focusProxy。新增None来源必须拒绝的邻近断言。
  - 回归点：19下载控制器/交付用例及限定Ruff通过；15次逐进程、同offscreen环境真实点击下载稳定性验证进行中D:/ZQ-Acceptance/download-probe-a76eacfadf894cfaa675015ed9d9bf9c。之后仍须完整回归，不能据当前绿灯宣称整个G06通过。
  诊断中一次15个同文件pytest收集批次未进入执行，已通过原会话中断并确认exit1；该批次不计下载失败/通过，改独立进程执行。未修改正式文件、生产代码或云端。API0元，目标active。

- 本轮全量未通过：D:/ZQ-Acceptance/r-134c26f41ef54c2ab27c496eb59245ef，客户端206通过、服务端153通过、平台668通过/1失败，runner退出1。失败test_real_http_download_confirm_complete_and_decline；不可将专项绿灯或后续孤立绿灯替代全量通过。
  - 现象：/one已到本机HTTP服务，downloadRequested后为DownloadCancelled，未调用选择路径、未创建下载记录，20秒超时。
  - 故障层：浏览器execution/compatibility的下载来源与初始生命周期层；不是模型调用/业务计算，具体根因尚未确认。
  - 证据：全量trace requests=['/one'], rejected=[], states=['DownloadState.DownloadCancelled'], loaded=[True], selections=[], records={}；单独复测1通过，再--keep-duplicates连续3通过（D:/ZQ-Acceptance/download-diagnose-one及download-diagnose-repeat3）。
  - 最小下一动作：测试诊断加入has_page/owned_page/save_page/controller_closed布尔值，继续复现区分原生无来源页、会话门禁与Qt早期取消；尚无证据支持修改生产下载门禁或放宽超时。
  - 回归点：真实HTTP首次/拒绝/隐藏进度/中断/冷恢复，以及完整平台；保持未交付文件不发布、无来源页不可接受的安全边界。
  本轮18关联与限定静态通过；共享模型限制及摘要反馈已修改。实际浏览器工厂/自然语言入口仍待接，暂停进入下一优化轮直至回归失败定位。API0元，无打包/推送/部署，目标active。

- 2026-09-17 G06模型资源与用户反馈：先以占满两个model名额的真实Qt线程测试复现浏览器绕过资源限制，再将BrowserProposalWorker接入CLIENT_RESOURCES可取消lease；等待取消不调用服务，成功/异常均释放。另以KeyError红灯复现宿主丢弃模型澄清/结果摘要，保存仅summary/evidence有界字段并反馈到原会话，needs_input明确提示补充信息，不将模型完成建议等同成功。18专项/邻近及限定Ruff/Mypy通过。全量进行中D:/ZQ-Acceptance/r-134c26f41ef54c2ab27c496eb59245ef。实际浏览器工厂与自然语言入口尚未联通，真实模型/OA未验；API0元，未发布部署，G06和目标active。

- 浏览器宿主轮完整回归结束：206客户端+153服务端+668平台=1027 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-9c073d86caf448dba5e026ce8169c7d4。17专项/邻近、新增模块Ruff/Mypy通过。下一步连接真实原生适配器工厂与自然语言入口，并补共享模型资源并发限制。G06及总目标active；未EXE/推送/部署，API累计0元。下条“全量进行中”为当时过程记录，现以本条结束结果为准。

- 2026-09-17 G06浏览器任务宿主：缺模块红灯后新增BrowserTaskHost，复用主窗口register_task_worker/TaskEventRelay与既有计划/授权/任务表，GUI线程认领一次；步骤终态、任务结果和事件在同一事务落盘。模型finish仅触发可信宿主验证，验证期间取消或撤权不能成功，未知状态不重放；对话新增浏览器结果分支，避免误报资料预检完成。17专项/邻近测试及新增模块Ruff/Mypy通过。全量进行中D:/ZQ-Acceptance/r-9c073d86caf448dba5e026ce8169c7d4；真实Qt主窗口配合合成runtime测试，不冒充实际网站自然语言端到端。实际适配器工厂、自然语言入口与真实网站验收待接通；API累计0元，未打包推送部署，目标active。

- 浏览器执行循环轮全量结束：206客户端+153服务端+667平台=1026 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-624278a8d7014753b462c2ec718deafb。18关联及限定Ruff/Mypy通过。下一步宿主适配现有register_task_worker/TaskEventRelay、持久认领与终态，以及routing_finished browser分支；循环测试使用真实Qt网络线程及合成页面，不冒充实际浏览器自然语言业务验收。G06及目标active，未打包推送部署，API累计0元。

- 2026-09-17 G06 GUI浏览器执行循环：新增browser_execution_loop，GUI线程启动/观察/派发，独立QThread仅请求客户端动作建议；复用BrowserObserver/Navigation、活租约与宿主持久授权回调，每次动作后重观察，32次建议上限，观察/动作45秒看门狗。模型错误/网页未知结果终止为unknown，不自动重试写；用户取消/接管/撤权拒绝后续动作，网络线程真正退出前保留QObject且不提前发终态；finish仅发needs_verification，不伪造业务成功。缺模块红灯后真实Qt线程+合成浏览器适配器验证动作→观察、取消/接管、未知不重放、网络迟到不派发、未退出线程保留、finish非成功。限定Ruff/Mypy通过（既有pywin32类型豁免）。宿主任务认领/终态持久化/窗口routing_finished仍需接线，测试动作门禁为合成，不能称已可在产品中发自然语言执行；可信登录/上传/滚动等待仍待完成。真实API累计0元，未发布部署。

- 浏览器下一步建议轮全量结束：206客户端+153服务端+665平台=1024 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-75dd2149b6df4d829e9f7943386f0132。36关联、新增模块限定Ruff及3模块Mypy通过，宽检查既有规则告警保留。下一步客户端GUI线程任务执行循环与远程建议worker，接实际租约/确认/取消/接管，之后才能启用自然语言入口。Zeabur控制台Dockerfile覆盖仍未同步，不误称新接口已上线。G06与总目标active，API累计0元，未打包推送部署。

- 2026-09-17 G06服务端下一步建议：新增Qt无依赖browser_contracts，复用现有观察结构并由BrowserObserver导入；BrowserStepRequest有限goal/范围/观察/1..32序号，BrowserStepProposal拒绝任意代码/密码字段、未观察控件、错误控件类型/选项、越界导航及无原文证据finish。finish只为待宿主核验建议，不视为业务成功。新增鉴权/api/v1/agent/browser-step与能力标识，复用metered.execute及browser:request_id，不新建计费；客户端propose_browser_step能力/取消/响应复验。Dockerfile和导出清单补共享模块，API文档指向运行时完整schema。11缺功能红灯及3客户端红灯后36关联通过，3模块Mypy通过；新增模块限定Ruff通过，包含既有api.py/remote_auth_service.py的宽检查仍有47项B008/异常捕获告警，未误报全局静态通过。实际宿主执行器/登录/上传/滚动等待未联通，真实模型与OA未验；API累计0元，未发布部署。

- 浏览器理解分型轮全量结束：203客户端+140服务端+665平台=1008 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-59e87667f3f94c56b85045f538a6be98。54关联与限定静态检查通过。后续接app.py routing_finished的browser分支、GUI线程原生执行器与服务器受控下一步动作建议；未启用未完成功能目录，真实模型/OA仍待验收。G06及总目标active，未EXE/推送/部署，API累计0元。

- 2026-09-17 G06浏览器理解分型：共享agent_contracts新增browser决策/BrowserIntent（有限规范HTTPS origin及原生动作，无密码代码权限字段），仅声明browser.task能力的请求可接收，禁止混入文件目标/文件计划；旧非浏览器结果序列化省略browser字段。服务端理解提示更新，不将OA特殊硬路由；AgentController由宿主显式browser_enabled启用目录，默认关闭，外部候选不能冒充原生浏览器。build_understood_browser_task复核共享契约并保留请求ID、原始要求和理解目标/限制，不发放授权、不自动执行。首轮3红及追加2红后实现；54关联通过，限定Ruff/3模块Mypy通过（既有pywin32类型豁免）。Mypy定位原EvidenceRef字典列表类型，改为显式model_validate，保留相同字段过滤。全量进行中D:/ZQ-Acceptance/r-59e87667f3f94c56b85045f538a6be98；模拟模型，未真实语义验收；实际窗口尚未开启browser_enabled，需浏览器执行器及宿主状态接通后启用，不能称端到端可用。API0元，未发布部署。

- 无附件浏览器协议轮全量结束：203客户端+140服务端+652平台=995 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-9104029a68334da9ae459401bbeeb9c7。56专项及限定静态检查通过。下一步共享UnderstandingRequest/TaskUnderstanding的浏览器意图分型与本地实际执行接线，必须保留文件意图非空目标、安全澄清与跨域权限门禁。G06未完成，总目标active，API累计0元，未发布部署。

- 2026-09-17 G06无附件浏览器任务协议：新增browser_task_spec/BROWSER原生能力及browser.execute契约，复用TaskSpec/ExecutionPlan/ExecutionStore/PermissionService，不建立平行任务库；浏览器步骤允许零文件、明确HTTPS origin/action/environment范围，不自动继承历史文件或记忆。ExecutionPlan仅浏览器步骤豁免非空输入，文件工具仍拒绝空输入；浏览器步骤暂不接受文件，上传成果将另走授权适配。发现文件预检步骤可取得浏览器回执的失败测试，PermissionService补mode/权限/步骤tool及网站动作环境校验，旧回执用例改用真实browser_task快照，不再用preflight冒充。9红1绿后实施，56专项通过，限定Ruff及3模块Mypy通过（pywin32类型豁免延续）。全量进行中D:/ZQ-Acceptance/r-9104029a68334da9ae459401bbeeb9c7；仅协议及存储接入，实际browser.execute执行器/自然语言调度仍未接，不能称端到端可用。API0元，未打包推送部署。

- 原生确认轮完整回归结束：203客户端+140服务端+638平台=981 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-0dd3490e4e5c469fb545524ccdfb0951。下一步复用ExecutionPlan/TaskSpec支持无附件浏览器任务，同时保持文件工具非空输入约束，再接自然语言和宿主确认状态。G06及总目标active；未打包推送部署，API累计0元。

- 2026-09-17 G06原生动作确认：新增browser_action_prompt，纯文本详情展示精确网站/环境/任务/动作/目标/内容（选择操作展示选项文字），明确勾选后才启用单次允许，取消默认，25秒过期、100ms检查任务失效，close撤销在途确认，非GUI线程/重入拒绝。先缺模块红灯后真实Qt弹框接BrowserActionGate及SQLite回执测试通过，20关联通过、限定Ruff/Mypy通过（既有pywin32类型豁免保留）。首张离屏截图字体方框，测试显式加载本机微软雅黑后重新验证，截图D:/ZQ-Acceptance/action-prompt-final/test_native_action_prompt_rece0/accept/confirmation.png已检查，HTML按字面显示。UI技能仅用于原生语义、焦点、留白，不套用落地页/移动端设计。全量进行中D:/ZQ-Acceptance/r-0dd3490e4e5c469fb545524ccdfb0951；尚未接产品自然语言入口和真实浏览器TaskSpec，is_active仍需由宿主绑定；不等同完整G06验收。API0元，未发布部署。

- 动作门禁连接轮完整回归结束：203客户端+140服务端+637平台=980 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-9070e9e44142429985764d80d6cf1870。45专项、限定Ruff/Mypy通过。下一步原生确认窗口、实际浏览器TaskSpec/工具目录与自然语言调度闭环；不把合成测试resolver当成已接产品入口。G06及总目标active，未发布部署，API累计0元。

- 2026-09-17 G06动作门禁连接：新增browser_action_gate，将BrowserObserver的click/edit原生回调连接PermissionService持久单次消费；由可信resolver读取执行上下文，绑定实际租约、观察nonce/完整观察及填写值摘要，确认前后重取scope与活租约，拒绝环境不一致。3缺模块红灯后接通，复查新增环境错配1红并修复；45动作/权限/迁移关联通过，限定Ruff及3模块Mypy通过（import-untyped豁免延续）。测试覆盖拒绝、确认中换claim、用户接管无回执/无派发、派发前已消费；使用合成页面和既有执行测试任务，尚未连接真实原生确认窗口、自然语言路由和浏览器TaskSpec，不冒充端到端验收。全量进行中：D:/ZQ-Acceptance/r-9070e9e44142429985764d80d6cf1870。API累计0元，未EXE/推送/部署。

- 持久动作授权轮全量结束：203客户端+140服务端+632平台=975 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-4cf6d8705d4a4db2bd0337352baf2763。接续G06执行入口与持久回执连接；未达到真实自然语言浏览器、OA或三端共同验收，未打包推送部署，真实API累计0元。

- 2026-09-17 G06持久动作授权基础：复用PermissionService而非独立权限库，提取事务内_verify；新增BrowserActionRequest严格绑定identity/step/revision/claim_token/environment/tab/page/origin/action/target/payload摘要。authorize_browser_action须原生明确确认和有效总任务receipt、正在运行的注册步骤及执行claim；回执60秒、同绑定重复授权幂等，已消费/过期不能重新发放；consume在BEGIN IMMEDIATE内原子标记，先消费后派发，崩溃不自动重放。schema7增量新增browser_action_authorizations，仅摘要/ID/时间，不存填写原文，沿用旧迁移备份/回滚/活动任务拦截；新store同步建表。4缺功能/迁移红灯、补claim字段红灯后33关联通过：重启不能重复消费、并发仅一胜、错目标/跨owner/总撤权/过期/终态/换claim拒绝、v6备份与DDL失败回滚。限定Ruff/Mypy通过（原pywin32类型限制延续）。尚未接BrowserObserver的实际UI确认回调、计划路由与自然语言入口；本轮使用既有preflight测试run验证通用执行记录边界，不冒充真实浏览器任务端到端。API0元，无发布部署，目标active。

- 普通表单轮全量结束：203客户端+140服务端+625平台=968 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-a84cc60b312741b39ddf51c9920e50b4。下一步滚动/等待及实际工具目录和持久任务授权连接，G06未整阶段验收。API累计0元，未真实网站写入/发布/部署，目标active。

- 2026-09-17 G06普通表单动作：browser_observation补带标签的普通input/textarea与单选select描述（无当前值/内部option值），敏感type/autocomplete/name/id/aria-label/关联label特征排除；选项只返回编号与文字，禁用/隐藏项不提供。固定action_script复用一次观察、DOM/字段/命中重验，fill通过原生value setter，select按原option索引，发送input/change但不调用submit。网站事件可能自动保存，不能把填写宣称无远端副作用。BrowserObserver扩展strict Choice/Control及独立can_edit，绑定目标/动作/具体value，默认拒绝、错kind/未知选项拒绝，沿用许可后再验及unknown规则。缺脚本1红、缺can_edit入口红、普通text字段Password标签1红后修复；9关联通过，另真实Qt租约→observer→can_edit→DOM填写完整链路通过，限定Ruff/Mypy通过。完整回归进行中D:/ZQ-Acceptance/r-a84cc60b312741b39ddf51c9920e50b4。仅合成页面；字段特征不是万能敏感识别，can_edit仍需真实持久业务授权/自然语言工具接线。复杂富文本/多选/iframe及滚动等待仍待完成。API0元，无发布部署。

- 原生导航轮全量结束：203客户端+140服务端+622平台=965 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-cfa09706ec5b41d6875fdc7d3a1ee0a9。G06仍doing；下一步填写/选择、工具目录与持久任务授权，尚未通过真实自然语言浏览器/OA端到端。未付费、打包、推送或部署，目标active。

- 2026-09-17 G06原生受控导航：新增browser_navigation，绑定注册页面/活任务lease、可信同步URL策略，单个在途导航、30秒计时/停止仅当前页、loaded仅页面加载而非业务成功。BrowserPage新增任务主frame导航门禁，302等跳转逐次校验，错误在Qt边界fail-closed且不回显敏感URL；站点资源策略仍沿用原有规则，非全站网络沙箱。手动takeover清除旧guard，取消仅失效不自动放宽在途跳转；真实HTTP测试发现取消后lease已释放导致guard残留1红，新增原生接管清理修复。初始缺模块1红后真实本机HTTP允许路径加载、直接越界/302越界拒绝且服务未收到目标路径、取消→接管后手动恢复通过；47导航/租约/policy/窗口关联通过，限定Ruff/Mypy通过。完整回归进行中D:/ZQ-Acceptance/r-cfa09706ec5b41d6875fdc7d3a1ee0a9。仅本机合成HTTP，不是TLS/OA业务验收；导航策略仍需接持久授权和模型工具目录，计时/进程终止还需专项。API0元，无真实站点修改/提交/发布/部署。

- 点击核心轮全量结束：203客户端+140服务端+621平台=964 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-27dc25a30ea6445a8b6380a5bc8a0737。未改全量运行中的源文件。下一步通用导航/填写/选择与实际任务授权、工具注册接线；现有点击不代表业务完成，G06仍doing，目标active。

- 2026-09-17 G06观察目标点击：browser_observation新增固定click_script，隔离世界MutationObserver/待处理记录、元素引用、字段当前值、30秒期限、目标可见/命中/禁用、链接HTTPS同源及表单POST同源目标复核；每次尝试消费观察，默认不允许跨站/下载/新窗口点击（这些需另走受控工具）。browser_observer新增本地can_click动作门禁，默认拒绝，原生观察对象/快照绑定；授权回调后再次校验lease/epoch/nonce，防确认期间接管。返回dispatched/rejected/unknown，不宣称点击等于业务成功；迟到不确定不得盲目重试写。DOM缺函数1红、控制器缺入口2红、确认期间接管1红均已复现修复；无视口测试最初命中拒绝，补实际QWebEngineView而未放宽命中检查。9关联含真实Qt观察→授权→点击计数、一次性/DOM及字段变化拒绝通过；限定Ruff/Mypy通过。完整回归进行中D:/ZQ-Acceptance/r-27dc25a30ea6445a8b6380a5bc8a0737。can_click仍为测试注入，需实际持久任务/业务范围授权接线；网页自身点击处理器无法由此保证业务回执。API0元，无真实站点写入/发布部署。

- 观察核心轮全量结束：203客户端+140服务端+618平台=961 passed，runner退出0/ok；证据D:/ZQ-Acceptance/r-0e3c5c9d2e7144d19c4b359956bd319b。G06-01/02已据实从pending改doing；下一步固定动作与DOM目标重验、持久任务授权/自然语言调度。原有下载超时和目录WinError5风险仍未确认根因；本轮未重现不代表修复。未扣费/打包/推送/部署，目标active。

- 2026-09-17 G06有界观察核心：新增browser_observation固定ApplicationWorld脚本，主frame/HTTPS、CSS隐藏/脚本/iframe/表单值排除，输入值直接重复遮蔽，12000字符/200控件/节点及字段扫描上限，显式truncated；只返回origin，不返回带查询的URL，控件引用留隔离世界。新增browser_observer，原生lease/任务活性/当前origin的可信can_observe回调双次验证，导航/接管/权限撤销/关闭丢弃迟到结果；严格Pydantic输出，untrusted=true。1缺脚本+2缺控制器红灯后6关联通过，包含真实Qt DOM+租约+observer接线，不仅脚本单测；限定Ruff/Mypy通过。完整回归进行中D:/ZQ-Acceptance/r-0e3c5c9d2e7144d19c4b359956bd319b。仅合成网页，无真实站点读取/模型外发；can_observe仍需接持久任务授权，page_version当前为原生导航epoch，DOM变化重验/通用操作/自然语言工具调度仍待完成。排除和直接值遮蔽不等于任意网站敏感信息DLP，网页可能在其他位置编码展示秘密，不能据此宣称所有秘密已过滤。API0元，无发布部署。

- 标签租约轮全量结束：203客户端+140服务端+615平台=958 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-4a284de469304414b88c67d51c9d91ba。源文件在回归期间未改动。G06继续doing，下一步通用受控浏览器工具/页面版本/有限脱敏观察与实际任务授权连接；不得以租约单测代替OA业务回执验收。目标active，尚未提交、打包、发布或部署。

- 2026-09-17 G06原生标签租约：新增browser_task_leases，复用现有TaskManager校验worker归属/运行/取消；按注册页面排他占用，旧lease对象不能释放后来lease，接管/关闭撤销同标签登录许可。BrowserPanel接实际window.task_manager，注册/关页/切账号清理；browser_takeover使用Qt应用事件过滤器观察面板内原生鼠标/键盘/输入法/滚动/触摸输入，仅撤销对应标签且不吞用户事件。3缺模块红灯及真实Qt窗口缺入口1红后实现；9关联通过，包括地址输入/网页点击接管、不影响另页、隐藏保留、取消失效；限定Ruff/Mypy通过。Qt事件过滤器参考https://doc.qt.io/qt-6/qobject.html#installEventFilter。完整回归进行中：D:/ZQ-Acceptance/r-4a284de469304414b88c67d51c9d91ba。自动化仍须每动作检查lease，并未向模型开放通用工具；测试使用合成任务worker，实际业务工作线程及OA端到端待验。API0元，无发布部署。

- 2026-09-17任务填充本轮完整回归结束：203客户端+140服务端+612平台=955 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-1a2b7e9981cc49808f39eb582240b994。未重启重复测试；服务端既有Starlette/httpx弃用警告保留。下一步将原生任务状态与标签排他租约接通，之后才向自然语言工具目录开放受控操作；当前目标active，未进行真实OA登录/上传或收费调用。

- G06可信任务填充接线：TrustedLogin新增可选原生tab_id、权限服务及当前任务scope resolver，fill_for_task消费单次许可后复核owner/environment/tab/page/origin，再走vault._for_agent_fill；手动fill保留原路径。导航/关闭撤销标签许可；任务取消或scope改变后的迟到回调不报告成功（已派发DOM操作不承诺撤回）。9缺入口红灯后27关联通过，补迟到取消1红后修复；真实Qt合成HTTPS-base DOM+DPAPI验证未授权拒绝、允许后填充、撤销再拒绝，未自动submit。34初轮专项，最终18填充/DOM关联及限定Ruff/Mypy通过（既有pywin32类型限制保留）。完整回归进行中：D:/ZQ-Acceptance/r-1a2b7e9981cc49808f39eb582240b994。尚未接自然语言调度及实际任务/标签租约，当前resolver由测试注入；不宣称Agent已可自动操作OA。API0元，无新发布部署。

- G06权限底层本轮回归结束：203客户端+140服务端+602平台=945 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-62035a783dea4695b26ff14b2360c421。Ruff最终通过。该轮仅增加可信本地权限服务，不接受模型JSON自授权限；必须后续接入原生任务状态/标签生命周期、网站授权与可信fill，尚不能由Agent调用。无真实网站登录/上传、无API费用、未发布EXE/GitHub/云端；目标active。

- 网站账号Agent授权完成本轮验证：browser_credential_vault schema2新增DPAPI保护且绑定凭据密文版本的授权，保存密码默认不授权，替换/删除撤销；CredentialManager新增明确授权/撤销及确认期间版本变化保护，关闭确认不生效。6授权专项、22关联、限定Ruff/Mypy通过；完整203+140+591=934 passed，runner退出0，证据D:/ZQ-Acceptance/r-8df546dbdc334fb1b7c1432537f08b56。实际界面截图已核验；不代表Agent任务工具已接通。API累计0元，无发布/部署。
- G06登录任务权限底层：新增browser_task_permissions与test_browser_task_permissions，精确HTTPS来源、账号/项目/会话/任务/请求/步骤/版本/标签/页面版本绑定，原生对象一次性授权、60秒过期、撤销及关闭拒绝。10缺模块红灯，新增关闭后重授测试1红后修复；17权限及凭据关联通过，限定Mypy通过，Ruff导入格式已修正。尚未接Harness/标签生命周期或真实fill调用，不能称自动登录完成。新全量进行中，证据D:/ZQ-Acceptance/r-62035a783dea4695b26ff14b2360c421。WSL启动出现HCS_E_CONNECTION_TIMEOUT，改用cmd执行Windows虚拟环境，未改WSL配置。既有下载偶发超时、目录WinError5及Docker环境限制仍保留。

- SPA登录兼容：只读打开真实OA登录页https://zhongqinoa01.com/login，DOM确认form无method/action，账号/密码autocomplete=off，登录为type=button，因此旧POST门禁不能覆盖。按该结构新增真实Qt失败场景（候选等待超时），修改browser_login_scripts与browser_login_capture：允许无method/action的唯一主页面HTTPS登录表单，捕获用户激活的JS按钮；保留显式GET/跨站action/目标重验拒绝，probe固定mode，填充不点击/重放。对于SPA填充加native GET提交保护（preventDefault，仅阻止无POST的原生submit，不调用submit），避免密码进URL；不能据此防御同源网站脚本本身的行为。9专项通过，限定Ruff/Mypy通过。新增只读scripts/probe_browser_login_page.py，客户端BrowserSession/BrowserPanel/TrustedLogin实际访问OA，最终origin匹配、TLS正常加载与安全表单探测通过，submitted=false；证据D:/ZQ-Acceptance/browser-login-probe-0e78a2612bf44384b2a6b280b8037aa3/result.json。未输入真实凭据，未执行登录/上传，不代表完整OA验收。
  - 现象：首轮全量203+140+584 passed/1 failed，证据D:/ZQ-Acceptance/r-62eaa5e63b3140e98b6e5164291aa749；原有真实HTTP下载首笔等待终态超时。
  - 故障层：execution/网络事件时序待定位，不归因于SPA规则；尚未确认根因。
  - 证据：失败目录无正式下载文件；单独重现测试通过，全部浏览器107项通过，不能用这些通过抹去原失败。
  - 最小动作：仅给测试增加请求、拒绝、Qt状态、页面加载和选择记录诊断；不改下载生产逻辑，不延长/削弱20秒断言。
  - 回归：再次完整203+140+585=928 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-018b7f8bc72747cc9abf43587cc33f14；偶发下载超时仍列风险，不称已修复。agent-diagnose-runtime用于分层诊断，agent-tdd-fix用于SPA红绿测试。Docker Desktop Linux engine pipe仍不存在，CLI status未运行；未启动/改配置。下一步登录导航时序/多步骤、Agent网站授权与真实登录验证。API0元，无打包推送部署，目标active。

- 网页捕获及保存UI：新增browser_login_capture.LoginCapture，固定ApplicationWorld脚本与该世界专用QWebChannel，主页面用户激活的同源HTTPS POST表单提交才接收；nonce/原生页面来源复核，不阻止或重放网站提交。候选接PendingLogin，120秒QTimer丢弃，关闭/跨站/加载失败丢弃；导航不是成功判定。新增browser_login_save_prompt并接BrowserPanel，当前标签显示网站/账号、明确勾选“已成功登录”才保存/更新，暂不/不再询问，切标签/隐藏清除勾选，关页/切账号关闭捕获。真实Qt合成HTTPS-base DOM鼠标提交、MainWorld无qt入口、伪造提交/跨站目标拒绝、候选未保存、实际UI确认/拒绝/更新标记/never恢复、超时/关闭及输出无合成密码通过；修前缺模块/面板入口红灯，修后13关联。首次断言误将设置查询创建空库视为保存密码，改查无凭据记录和无明文，不放宽保存权限。限定Ruff/Mypy通过（pywin32类型限制延续），截图D:/ZQ-Acceptance/capture-ui-green/test_real_isolated_capture_and0/save-prompt.png已核对。完整203+140+585=928 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-440b62c01ddb4af48f74dec876ed0f85。UI技能用于原生语义控件/间距/明确状态，未采用不适用的移动端主题。Qt隔离世界/通道依据https://doc.qt.io/qt-6/qwebenginepage.html#setWebChannel及https://doc.qt.io/qt-6/qtwebchannel-javascript.html。本轮成功由用户明确确认，不自动推断；SPA/多步骤/跨域/真实TLS/OA、提交IPC与真实导航时序仍需专项验收；Agent使用授权未实现。API0元，无打包推送部署，目标active。

- 登录保存候选状态：新增browser_pending_login.PendingLogin，候选仅DPAPI加密留在内存，不在同意前写凭据库；绑定owner/environment/精确HTTPS origin/native flow ID，120秒使用期限，一次save尝试即消费。未明确同意或成功、取消、超期、来源/flow改变拒绝；替换仍须旧ID，never策略及密文错误不覆盖旧记录。10缺模块红灯后26凭据关联通过，限定Ruff/Mypy通过（延续pywin32 import-untyped类型限制）；完整203+140+584=927 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-648e14939bee48859b67c8255e4bc02c。该模块尚未接网页捕获/保存询问，期限目前在save时校验，UI需定时discard；Python不保证内存安全擦除，页面跳转不是成功登录证据。下一轮接可信捕获、生命周期失效及用户明确成功/保存确认，不称G05完成。API0元，无打包推送部署，目标active。

- 用户凭据填充UI：新增browser_login_actions.BrowserLoginActions，网站账号菜单增加当前网页登录填充；仅筛选精确origin的账号，原生确认框展示网站/账号及“不主动提交”，明确选择后接TrustedLogin。一次操作绑定当前view，切标签/隐藏/关闭/导航撤销待确认流程，迟到结果不改无关页面；TrustedLogin.close解除信号并使旧ticket无效。缺动作模块1红后真实Qt合成DOM+DPAPI+实际确认框接受/取消通过，11关联包括面板显隐/标签及生命周期通过；截图D:/ZQ-Acceptance/login-ui-green/test_login_scripts_real_dom_re0/fill-confirmation.png已检查。UI技能用于原生确认、状态和可访问语义，不照搬移动样式。限定Ruff/Mypy通过（pywin32类型豁免延续）；完整203+140+574=917 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-27afcd3cbd414ca098ac369f2f79f190。已派发给网页的单次填充不保证撤回，取消阻止后续动作；不构成Agent长期授权。保存捕获/询问/成功判定、SPA/跨域/验证码、真实TLS与OA尚未完成，下一步保存流程。API0元，无打包推送部署，目标active。

- 可信凭据填充核心：新增browser_login_scripts（固定ApplicationWorld探测/填充、主页面、可见未禁用控件、唯一账号/密码表单、HTTPS同源POST、内外部提交按钮目标检查；一次nonce/60秒有效、元素引用/原输入/表单action复核，无主动submit、返回无密码）及browser_trusted_login（session/page/vault归属、native来源、加载/导航/render退出失效、一次性对象ticket、过期/未确认不解密、迟到回调处理）。DOM缺模块1红、控制器缺模块3红后补实现；再复现错误账号vault绑定及None ticket两红、加载中探测1红后修复。13关联含真实Qt内存HTTPS-base合成DOM+真实DPAPI凭据链路通过，限定Ruff/Mypy通过（pywin32 import-untyped豁免延续）。完整203+140+573=916 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-2f2bb1216d2d46aca6eb4b115be7a6c4。Qt行为参考https://doc.qt.io/qt-6/qwebenginepage.html。未接UI填充/保存提示或Agent网站授权；仅单一同源POST表单，SPA/跨域登录/验证码及真实TLS/站点仍待适配与验收，合成baseURL不算TLS验证；同源网站取得填充值后的行为不作防恶意站点保证。下一步用户保存/填充同意闭环及自然语言浏览器授权。API0元，无打包推送部署，目标active。

- 网站账号管理UI：新增browser_credential_manager.CredentialManager，BrowserPanel网站账号入口懒加载；显示网站/用户名、不提供密码展示复制；删除账号、不再询问、恢复询问均本地确认（PlainText、默认No），关闭/账号切换使在途确认失效并reject确认框。凭据库新增blocked_sites查询；面板对已知WebEngine标签补类型cast，不改运行路径。缺入口1红后窗口动作通过，真实QMessageBox+QTimer关闭验证未删除旧凭据；10存储/界面/关闭关联及限定Ruff/Mypy通过（延续pywin32缺stub的import-untyped豁免，不称完整第三方类型验证）。UI技能用于原生控件、状态及间距，未采纳不适用的移动/落地页方案；截图D:/ZQ-Acceptance/credential-manager-green/test_browser_credentials_manag0/credential-manager.png已查看。完整203+140+566=909 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-f8c0c880ec7d4d88b3d185653fc29c66。未接网页密码捕获、成功判定、保存询问、可信填充和Agent使用授权，不能称浏览器凭据已完整可用。下一步上述可信上下文/同意流程。仅合成凭据删除，无真实网站凭据改动；API0元，无打包推送部署，目标active。

- 网站凭据存储基础：新增browser_secrets（真实win32crypt DPAPI当前用户、UI_FORBIDDEN=1、无LOCAL_MACHINE、无明文降级、错误脱敏）及browser_credential_vault（非系统盘账号/环境独立SQLite、用户名与密码整体加密、context绑定owner/environment/精确HTTPS origin/record ID）。保存要求明确同意及成功登录；替换须指定旧ID，失败/加密失败不覆盖；同站多账号、删除确认、不再询问/恢复询问、未知schema拒绝、数据盘缺失不重建。先2+4缺模块红灯后补实现，51凭据/策略专项通过；真实密文篡改和跨账号复制拒绝，测试落盘无合成用户名/密码明文。Ruff通过，Mypy因环境缺types-pywin32产生2项import-untyped；限定加--disable-error-code import-untyped后两模块通过，不称第三方API完整类型验证。完整203+140+565=908 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-97d3417ba8f44e408643705dc07813b1。尚未接网页密码捕获/保存提示/管理UI/可信填充；布尔同意参数不是Harness授权替代，不暴露为Agent工具。DPAPI不防同Windows用户恶意程序/已失陷主机，跨Windows账号解密未实测；参照https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata。下一步凭据管理与可信网页上下文/同意状态机。API0元，无打包推送部署，G05及目标active。

- 下载冷恢复：新增browser_download_journal.DownloadJournal（账号/environment Profile内SQLite，schema1），accept前登记唯一暂存路径、目标及目录设备/文件身份；登记失败取消，完成交付后去登记失败不改交付成功状态。BrowserSession仅首次取得进程Profile锁、构建Qt Profile前recover，同进程缓存复用不回收。只处理登记的同父目录.zq-download-*及两个已知文件，先检查全部内容，未知/替换/重定向/不可访问目录保留待处理，不遍历用户目录、不递归删除、不打开正式成果。4缺模块红灯后模块通过；真实HTTP缺session接线红灯后实现，两个独立进程验证取消退出→再次启动清理、正式成果保持，同进程重开保留；另验证篡改宽路径/登记异常拒绝。26专项、限定Ruff/Mypy通过。完整203+140+556=899 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-7997f9c3dd484b5bbecb985bf556e05f。仅清理了合成测试暂存，无用户文件被删除；强杀/断电及恶意本机实时文件替换竞态未宣称验收，异常保留项尚需可见管理入口。下一步网站凭据DPAPI/同意管理，浏览器Agent工具及真实站点仍待完成。API0元，无打包推送部署，目标active。

- 下载界面接入：新增browser_download_view.DownloadsDialog/DownloadRow，BrowserPanel底部下载入口；保存对话框从本账号显式非系统盘下载目录起步，危险建议文件名改download.bin，缺目录不回落。真实HTTP测试从控制器提升到面板+保存对话框回调+实际按钮取消，完整内容/字节、隐藏列表继续下载且进度不抢焦点、已完成/取消文案和按钮禁用通过；账号切换及正常/异常退出关联通过。UI技能用于原生简洁控件、状态文本、间距和可访问标签，截图D:/ZQ-Acceptance/download-ui-green/test_real_http_download_confir0/downloads.png已查看。完整203+140+549=892 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-e00d8064cb0045f29cc48f38f3292378。全量后复查新增数据目录索引SQLite异常1红，最小修为取消请求并脱敏提示；最终22专项、限定Ruff及两模块Mypy --check-untyped-defs通过（此最后保护未重跑全量，不虚增全量计数）。下一步取消暂存持久记录/跨进程安全回收，再网站凭据及Agent工具；G05未完成。API0元，无打包推送部署。

- 下载控制层：新增BrowserDownloads，绑定当前BrowserSession页面归属，网页保存/非HTTP(S)/外来页面拒绝；调用保存位置确认回调后才创建暂存和accept，模态回调返回再次检查会话。记录实际received/total字节（未知总量不伪造百分比），完成才交付，重复终态无重复写入；关闭断开新请求并取消在途。3缺模块红灯后17模拟/落盘测试通过；真实本机HTTP验证确认、拒绝、内容/字节一致及传输中关闭取消。真实取消复现Qt终态后后台再次创建暂存目录，取消改为保留隔离暂存并标cleanup_pending，不误报清理完成；冷恢复清理尚待实现。18专项、限定Ruff/Mypy通过；完整203+140+549=892 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-72249cd5582649958e98972b9155be9a（平台509.74秒）。控制层尚未接BrowserPanel保存对话框/下载列表，不宣称客户端下载已交付；下步UI及安全恢复。API0元，无打包推送部署，G05及目标active。

- 下载落盘基础：新增browser_downloads.DownloadTarget，非系统盘绝对且未重定向目标、Windows危险/设备/流文件名拒绝；目标父目录中新建唯一暂存目录，下载正文先写payload.part，完成后同卷硬链接原子不覆盖交付，再清理已知暂存。晚到同名文件保留原件及暂存；取消只清理本次两个已知文件、不递归删除未知内容。13缺模块红灯后通过；另复现交付成功但空暂存目录删除失败造成误报，改为独立cleanup_pending，14专项及限定Ruff/Mypy通过。完整203+140+545=888 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-3db2cd6185c84ca29b6133f9121ea9fe。此轮尚未接QWebEngineDownloadRequest/确认/进度/取消界面，不宣称真实下载已可用；不支持硬链接的文件系统保留暂存并报错，未降级覆盖。下一步真实HTTP下载和浏览器信号闭环。API0元，无打包推送部署，目标active。

- 浏览器弹窗：BrowserPanel接newWindowRequested，用户鼠标/键盘触发且安全URL的新窗口放入同账号Profile标签；后台目标不抢焦点，非用户触发/危险URL拒绝，标签达到12个时不再接受弹窗；接收openIn时不先加载about:blank以免覆盖目标。缺open_popup红灯后请求边界/上限专项通过；新增真实本机HTTP网页，QTest鼠标点击target=_blank，实际信号isUserInitiated=True、目标标签URL及Profile均验证。2关联及限定Ruff/Mypy通过；完整203+140+531=874 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-f66ca2020997455d8592c46eff543fd8。自动弹窗拒绝仍须未来提供必要的受控例外交互，第三方/OA登录弹窗未验收；下载/密码/Agent工具仍未完成。下一步下载确认、非系统盘保存及取消。API0元，无打包推送部署，目标active。

- 浏览器主页与书签：新增BrowserLibrary，账号/production-test分库存放用户主动保存的网址与名称，默认about:blank，重复URL更新标题，删除/主页设置明确操作；拒绝危险协议及网址凭据，缺盘不重建，未知库版本拒绝。6缺模块红灯后6存储专项通过；面板增加原生主页按钮/书签菜单，名称确认、设置/删除确认及取消、真实菜单动作纳入窗口测试。动态QMenu生命周期红灯后显式父对象+持有子菜单，重复刷新和打开验证通过；7关联、限定Ruff/Mypy通过，截图library-ui-green-04已查看。UI技能用于原生简洁菜单及可访问标签，未照搬不适用的移动/餐饮样式。完整203+140+530=873 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-cb77b0831137481f878fa6ed1dfa6868。不自动采集历史、不保存密码或上传书签；弹窗、下载、网站凭据及Agent浏览器仍待接入。API0元，无打包推送部署，目标active。

- 浏览器状态与异常退出修复：新增确定性断言复现旧加载完成抹掉错误提示，并验证后台标签不得覆盖当前地址/提示；面板按view保存notice/loadStatus/addressDraft，真实导航前清理输入状态。独立子进程合成RuntimeError在活浏览器下稳定返回3221225477而非Python异常码1；修正进程Profile清理为关联view→page→profile→租约，正常直接退出/未捕获异常两个对照分别返回0/1，未掩盖原异常。46浏览器专项、限定Ruff/Mypy通过，完整203+140+524=867 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-2569d74cf9ed45e6bc806444b1504d36。此证据只覆盖已复现的销毁次序，不宣称全部原生崩溃/强杀/断电已解决；浏览器主页书签/弹窗/下载/密码/Agent工具仍未完成。下一步浏览器功能及授权操作闭环；API0元，无打包推送部署，目标active。

- 通用浏览器面板首轮接入：新增BrowserPanel（原生导航按钮、地址栏、多标签、加载状态），PlatformWindow右上角懒加载入口及右侧浏览器页；默认about:blank，不绑定OA；隐藏保留页面，账号切换先销毁旧账号页面，关闭窗口释放页面但Profile目录租约持续至进程退出。先缺toggle入口红灯，账号切换遗留页红灯后修复；截图发现内容360px/容器312px截断，增加尺寸失败断言并将浏览器容器最小宽420px，关闭恢复250px。6关联通过，窗口/面板/测试Ruff、面板Mypy通过；截图D:/ZQ-Acceptance/panel-layout-green-06/test_window_browser_tabs_hide_0/browser-panel.png已查看。UI技能用于中性原生控件、键盘可访问与间距，不改Qt栈。完整203+140+522=865 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-162da88d61d7410d8045ced9f49c86e0。失败断言中未正常关闭Qt窗口的子进程曾返回原生异常退出，正常清理路径专项及全量通过，不能据此称所有异常退出已消除。下一步完善状态更新（无效输入提示可能被前次加载信号覆盖）、浏览器异常退出清理、弹窗/书签/下载及授权上传；密码库/Agent工具/真实站点未完成。API0元，无打包推送部署。

- 浏览器页面/请求双门禁：新增BrowserPage、BrowserRequestInterceptor，Profile/new_page正式使用；导航拒绝本地/脚本/凭据地址，请求层拒绝宿主协议，普通HTTP及子资源data/blob/websocket按策略保留；证书错误、网站敏感权限、文件系统访问默认拒绝，上传等待具体成果授权流程，不提供宿主桥。12缺入口红灯后策略通过；旧setHtml数据页因安全策略被拒绝，改用真实本机HTTP合成页并加入302到file拒绝、凭据不回显、未授权文件选择返回空。测试脚本漏导入修正后40专项通过，追加拦截器接线3项后43通过。完整203+140+521=864 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-d73c3b90408c479fbe685b533ecb67a6；全量后仅修测试import格式，再测43通过，限定Ruff/Mypy通过。当前并非完整通用浏览器：面板、弹窗许可、下载、凭据库、授权上传及真实TLS/站点矩阵仍待接入；下一步面板。API0元，无打包推送部署，目标active。

- 浏览器Profile生命周期：新增browser_profile.BrowserSession，使用显式StoragePreferences租约、非系统盘账号/production-test隔离目录、QLockFile进程互斥；从不调用defaultProfile，关闭本地资源/剪贴板/混合内容/插件权限，网站权限每次询问。独立真实WebEngine测试先缺模块红灯，初版销毁profile后立即迁移两次失败；现场确认Chromium临时文件在枚举后消失。改为应用进程级Profile池，同账号关闭页面后复用Profile，目录租约保持至进程退出，退出后再迁移；不通过忽略临时文件或放宽inventory规避。Python3.10 Self导入失败改typing_extensions后33关联及限定Ruff/Mypy通过；补真实合成页面加载和跨进程锁验证通过。完整203+140+506=849 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-40ffb0b8c06a4072b802701178cfb876。尚未接界面/请求拦截/密码库；未来迁移界面须明确浏览器使用后重启再迁移，不能声称关闭页面即可迁移。下一步安全页面与请求门禁、通用面板；API0元，无打包推送部署，目标active。

- 通用浏览器安全策略第一轮：新增browser_policy，明确HTTP/HTTPS及about:blank导航，拒绝本地/脚本协议、夹带凭据、反斜杠/控制字符和畸形地址；保存凭据仅接受HTTPS精确origin，保留非默认端口并规范IDN/IPv6；拒绝继承关闭沙箱、证书校验、同源保护或开放远程调试的配置。20缺模块红灯后补实现，扩展边界后27策略+7存储=34专项通过，限定Ruff/Mypy通过。完整203+140+505=848 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-d5990751fae64a09b22be571fe63b30a。当前仅策略模块，尚未接入真实页面/请求拦截/Profile/客户端面板，不声称浏览器安全验收通过。下一步账号隔离Profile与存储使用锁，再接通用面板。API累计0元，无打包推送部署；目标active。

- 大型导航查询优化：新增100项目/1000会话/20000助手消息合成测试，以SQLite VM指令预算限制检测重复扫描；旧查询在第几个项目即超过200万步红灯。改为每数据库集中统计未读及会话，再按项目装配；目录索引中同库项目共享一次只读快照，不新增索引/迁移、不缓存跨轮结果。单库及catalog同库100项目分别约0.016/0.094秒，1014000/1015000 VM步；保留全部1000会话、逐会话20未读。增加账号、归档、已读/用户消息边界测试，12关联及限定Ruff/Mypy通过。完整203+140+478=821 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-ad0672177fae49faa839f052b89bcd01。性能数据只代表本机查询合成样本，不代表网络盘/全部实机或UI绘制吞吐。下一步通用内置浏览器安全基础，G04云端并发/真实桌面仍未完；API0元，无打包推送部署。

- 项目树只读快照/锁隔离：复现状态刷新依赖PlatformStore初始化（1红），新增navigation_snapshot以mode=ro/query_only事务读取账号范围内项目及会话，不创建、初始化或迁移数据库，busy timeout=0；不可用项目独立标注。背景项目锁专项通过后发现当前项目旧会话状态读取仍阻塞约21秒（真实BEGIN EXCLUSIVE红灯），将列表和树状态改为共用只读快照。15关联通过，验证跨项目运行/未读、锁释放恢复、当前输入/会话保持、缺失数据库不重建、旧schema不迁移；限定Ruff及两模块Mypy通过。完整203+140+475=818 passed，runner退出0/ok，证据D:/ZQ-Acceptance/r-369ac4de97df4de9b0a9385b5a0850df。此为SQLite锁等待及初始化副作用修复，不声称慢磁盘/大量项目已全部验收；大型导航刷新及实机仍待补。API0元，无打包推送部署，G04仍doing。

- 项目树第一轮：新增ProjectTree可展开多个项目会话，ProjectCatalog.project_store只读取指定项目而不改变active/selection；统一可见导航，内部复用隐藏选择控制器。树刷新按ID更新保留展开/选中，显示分支来源、运行及未读状态；右键支持新建/重命名/归档。跨项目草稿切换1红后10关联通过；补新建会话仍选旧项、分支tooltip参数错误两红后最小修复，22关联及限定Ruff通过。完整203+140+472=815 passed，runner退出0/ok，三JUnit0失败错误，证据D:/ZQ-Acceptance/r-9b6e61cff3c7400d818e0df60ac6ea2e。全量后仅调整树选择配色/缩进装饰，3树专项重测、两个新增/重构模块Mypy通过，并检查offscreen截图D:/ZQ-Acceptance/tree-visual-final-2923625/test_tree_background_unread_an0/project-tree.png。树大量项目刷新性能、跨项目运行状态/不可用目录专项、真实桌面操作仍需补；本轮不将整个G04标passed。历史WinError5环境风险保留；API0元，无打包推送部署。

- WinError5进一步诊断：新增只查询不终止进程的Windows Restart Manager探针，合成文件持有/释放能正确识别当前PID。失败现场RENAME_FILE_OWNERS=[]、timer=False；无Qt对照在仓库内nested_sqlite第2次、catalog第10次复现，证明不依赖Qt/Agent。普通文件和根目录SQLite对照通过；仍未查明具体过滤器/目录句柄占用者。仓库外D:/ZQ-Acceptance的同一组8测试通过，提示目录环境相关而非证明根因。首次外部命令因父目录未创建8 setup errors，创建专用测试父目录后执行，未修改业务资料。
- 为可重复环境对照，产品回归runner增加显式--artifact-root（绝对路径、解析后禁止系统盘、唯一子目录）；不变更源码cwd、测试范围、超时、退出码或JUnit门禁。1红后5通过、限定Ruff通过。完整外部产物回归203+140+469=812 passed，runner退出0/ok，三份JUnit均0失败/错误，证据D:/ZQ-Acceptance/r-78022665147f406382f16f9eaf877c8c。全量后仅补诊断失败不能覆盖原PermissionError的保护，6探针专项及Ruff再通过。仓库内占用原因保留未决，不加重试、不跳过失败测试、不改Agent生产代码来猜修；下一步继续项目树，同时保留实机目录移动环境验收。原分支Agent代码已包含在812回归中，真实语义未验；API0元，无打包推送部署。

- Agent分支理解接入：新增branch_understanding将校验后的分叉前完成结果投影为有run_id/结果摘要的只读参考，单任务及组合任务支持审核意见、生成成果名称/摘要、交付版本名称/摘要；不带路径字段、授权字段或自动加入本轮files。准备和接收模型回复时复核，澄清保留一次且核对一致；取消不因来源失效而受阻；超过协议上限拒绝而非截断。4红后12通过，补历史目标不能越权/组合结果/取消边界后24关联通过，限定Ruff/Mypy通过。完整r-39539366bc5a49ffa7b4d48aa61922e4为203+140+461通过、平台1失败（原test_reopen_restores_selected_session_and_missing_project_is_nonblocking，关闭窗口后rename WinError5再次出现），runner退出1，不能视为完整回归通过。下一步在失败现场采集占用证据，不以再重跑绿灯结案。真实模型理解尚未验收，API累计0元，无打包推送部署；不标G04完成。

- 目录移动间歇失败诊断：现象为窗口关闭后rename报WinError5，定位到execution/Windows文件操作层，尚无证据归因SQLite泄漏。检查PlatformStore.connect、ProjectCatalog.index及迁移器均显式close；新增TrackedConnection资源探针连续10次真实建项目/开窗口/processEvents/关闭/移动目录，逐次断言连接集合为空、timer停止，2测试及Ruff通过。未因猜测修改生产代码、未加重试或跳过断言。完整重跑203+140+455=798 passed，runner退出0/ok，证据outputs/nl_acceptance/r-9cc44b422fb94fc6bda712edbd133ca8；原间歇失败原因未确认，仍保留实机占用风险，不能称已修复。上一轮已有实际交付版本代码/证据进展；本轮推进资源释放验证，目标active。下一步Agent接收经过校验的分支只读事实引用，不自动带入旧附件或执行权限；API累计0元，无发布部署。

- 审核交付版本记录：标准Word导出及批注副本写入delivery_versions（绝对路径、SHA256、大小），组合步骤元数据单独保存，不修改不可变步骤结果；分支读取验证单任务/组合审核成果，替换、删除及缺少版本记录拒绝。最初两项缺版本红灯已记录；恢复后23关联通过，新增异常元数据3红后修复，单/组合报告与批注22关联通过，限定Ruff通过。完整回归r-a4e2c4b7131a4a1c82ff0cddb1926ad2为203+140+453通过、平台1失败：test_project_catalog_ui关闭窗口后目录rename报WinError5，runner退出1，不能记整体通过。失败项隔离1通过，交付版本/项目恢复/草稿邻近14通过；数据库连接检查已有finally关闭，尚不能证明占用来源，不猜测或加重试掩盖。下一轮先排查这一全量间歇失败，再继续Agent分支上下文消费及项目树；真实模型0元，无打包推送部署，G04仍doing。

- 后代分支引用继承：创建子分支时绑定祖先context_snapshot摘要；读取在同一SQLite读事务递归验证祖先账号/项目/锚点/固定结果，不纳入祖先分叉后完成的新任务。创建前限制追溯32层及总结果100条，重复引用拒绝，失败事务不留下新会话；不复制执行授权、附件选择或任务。后代缺祖先结果1红后17关联通过，追加深度拒绝/重复引用后9专项通过，限定Ruff/Mypy通过。完整203+140+447=790 passed，runner退出0/ok，证据outputs/nl_acceptance/r-45d854f0592548eb920052bcc3deba47。审核导出/批注副本版本记录、Agent消费与项目树仍未完成，G04继续doing；旧无祖先摘要的快照不追溯补入额外历史。真实模型0元，未打包推送部署。

- 分支生成成果核验：branch_context读取固定结果后复用artifact_path/step_artifact_path校验单任务及组合任务生成文件的范围、扩展名、存在性、摘要；单任务额外核对ok、名称和生成目录重定向，组合任务同时验证不可变步骤结果。替换/删除/目录外及真实合成工商Word组合成果4红后13关联通过。完整203+140+444=787 passed，runner退出0/ok，证据outputs/nl_acceptance/r-0b9bf71600ed431ab886e7aff232a47f。全量后仅将内部无效类型异常按Ruff改TypeError（调用边界仍包装ValueError），11关联重测及限定Ruff通过，Mypy此前通过。尚未覆盖审核导出/批注副本的固定版本记录、后代分支继承及Agent上下文消费，不据此标G04-02完成；真实模型0元，未发布部署。

- 分支结果引用第一步：新增branch_context.py；在分叉事务中仅枚举来源会话且有成功事件时间不晚于锚点的已成功任务，保存run_id和结果SHA256而非消息/结果正文/授权，最多100条超限拒绝。branch_results读取时核对账号、项目、父会话、锚点摘要、完成时间及结果摘要，任何结果变化拒绝采用；分支界面列出已校验任务引用，失败显示需回源核对。2红后12关联通过，限定Ruff/Mypy通过；完整203+140+440=783 passed，runner退出0/ok，证据outputs/nl_acceptance/r-4fa84a6627d5491494b5ee457f12082e。此为结果引用而非认定模型业务结论真实：成果文件路径/哈希逐项校验、后代分支继承、Agent受控上下文消费仍未接，G04-02继续doing；无收费、发布、部署。

- 指定消息分支入口：用户/助手消息下增加zq-branch链接，命名确认后由SessionService在原项目创建独立子会话并选中；来源消息锚点落盘，分支显示来源及返回父会话入口。校验当前session、消息真实归属、链接参数、标题及草稿保存状态；不复制附件/草稿/任务/权限，取消不创建。入口缺失1红后13关联通过，新增取消/错锚点/伪造参数后5专项通过，限定Ruff通过。完整203+140+438=781 passed，runner退出0/ok，证据outputs/nl_acceptance/r-8cb6276db6054f35b05a39284b1fe801，无本轮原生崩溃。完成事实/成果固定引用继承及项目树仍未实现，G04仍doing；旧崩溃风险不因本轮通过而宣称消失。真实模型0元，无打包推送部署。

- 草稿可靠性与项目切换：保存失败后切换丢输入已1红复现；新增按数据库/账号/会话固定的未保存内存快照，恢复可读，正常关闭/切账号/目录迁移前重试，未成功则拒绝。跨ProjectCatalog测试另复现sessions.clear中间信号使用新project_id/旧active store及附件丢失；切项目清列表阻断信号并清空无项目显示后6草稿专项通过。真正v5无draft表迁移注入失败验证原版本/历史/备份保留，恢复后迁移成功。测试初次插入位置误放重启断言导致NameError，已归回原测试，不削弱断言。
- 本轮首次完整203+140通过后平台在test_compound_window原生access violation退出255，证据r-ede65fd848574530be3db78992b7b53a，平台无完整JUnit，不能记通过。组合+草稿13项隔离通过；确定性新测试发现已关闭窗口QTimer仍active（1红），仅允许关闭时stop，19关联及限定Ruff通过。重跑完整203+140+433=776 passed，runner退出0/ok，证据outputs/nl_acceptance/r-727d4ce8119b47378374925183f0ee30。Qt底层访问冲突因果尚未完全证明，保留实机稳定性风险，不能宣称彻底解决；关闭timer的确定性缺陷已修。草稿内存保护不承诺磁盘不可写后强杀/断电恢复。真实模型0元，未打包推送部署，目标active；下一步继续消息分支/固定成果引用及项目树。

- 草稿隔离第一轮：新增schema 6 session_drafts，按真实session/owner校验并限定同项目附件ID、12000字/100附件、submitted标记；无默认复制到分支。SessionService读写两红后22数据层关联通过，窗口切换复现上一会话文字残留1红后接入固定store/session绑定；文本与勾选变更保存、程序化列表刷新阻断中间itemChanged信号、恢复会话加载对应草稿，已提交范围标志保存。14窗口/快捷键/拖拽关联通过，限定Ruff/Mypy通过。完整203+140+429=772 passed，runner退出0/ok，证据outputs/nl_acceptance/r-b4fa2cf89e624342aab69cdc562e052a。跨项目、附件恢复、保存失败时禁止丢输入及真正v5到v6迁移故障专项仍需补，不能标完整草稿验收。真实模型0元，未打包推送部署。上一轮为实际代码和验证进展，无连续阻塞。

- 会话运行/未读标记：新增列表定时状态刷新，不清列表或切换选中会话，后台助手消息显示未读数，打开会话保存单调已读位置；显示TaskManager中当前会话任务运行状态。缺入口1红后11关联通过；复查发现恢复历史前timer尚未创建，新增初始化失败测试1红后修正顺序，16关联通过及限定Ruff通过。完整203+140+426=769 passed，runner退出0/ok，证据outputs/nl_acceptance/r-33158b95bbf148eb8760ad9e083822e7。已读语义目前为打开会话，不声称逐条视口阅读跟踪；项目树、草稿及附件选择隔离、消息分支入口与完成事实继承待继续。58个G子项仍3 passed/16 doing/39 pending，不能将回归数折算完成率；真实模型0元，未打包推送部署。

- 会话界面第一步：右键会话提供重命名/归档，侧栏提供恢复归档会话；操作按当前项目/账号，重命名保留选中会话，归档需确认，TaskManager理解中任务也阻止归档。新增入口缺失1红后10关联通过，限定Ruff通过；完整203+140+424=767 passed，runner退出0并返回ok，证据outputs/nl_acceptance/r-76e4ca148f164e8d852581edad5c0cd1。仅当前项目会话列表入口，项目树展开、未读/运行标记、草稿隔离、消息分支UI及事实引用继承仍待完成。真实模型累计0元；未打包、推送、部署，目标active。

- 会话元数据第一步：本地schema 5以独立session_metadata表保存归档、已读游标、父会话、分叉锚点及快照，不改旧sessions列。SessionService校验账号、标题、同会话游标/锚点，已读单调前进，归档与start_run事务互斥；分叉仅记来源摘要，不复制消息、附件、动作或授权。专项先缺模块红灯后30关联通过；追加迁移故障回滚及归档任务拒绝用例纳入完整回归。三份完整JUnit报告203+140+423=766，errors/failures/skipped均0，证据outputs/nl_acceptance/r-434091dafc6a475d937bb9ac67c6dcb5；恢复上下文后重新检查限定Ruff/Mypy通过，未重跑收费调用。分支界面、草稿隔离、已完成事实引用继承尚未实施，不标G04完成。真实模型累计0元，授权总上限20元；无本轮打包、推送或部署。

- 后台审核批注询问：新增annotation_followup.ensure_questions，按真实账号/任务读取成功审核，消息与annotation_prompted在同一BEGIN IMMEDIATE事务保存，失败整笔回滚；组合任务仅向对应review_deliveries写标记，不改不可变steps。前台沿用确认窗口但共用原子落盘，后台完成只在原会话提问，不向无关会话弹窗，不写业务文档；重开会话能看到问题且不重复提问。2红后15关联通过，追加空结果/越权/组合checkpoint保护后15专项通过；限定Ruff/Mypy通过。完整203+140+418=761 passed，runner返回ok，证据outputs/nl_acceptance/r-7b277e3efe4e456ca30e78405075297d。异常退出发生在审核结束与询问落盘之间的恢复补问仍未验；分支/未读、真实并发与发布仍未完成。真实模型0元，无打包推送部署，目标active。

- 会话级调度已接窗口：移除全局worker存储，兼容只读worker属性按owner/project/session从TaskManager查找；任务运行仍可新建/切换项目和会话，当前会话发送/停止状态独立；后台任务存在时禁止切账号、目录迁移、Skill管理及归档等操作；关闭取消全部任务并等待实际登记释放，资源仍在途时也拒绝关闭/切账号。最小场景从1红到通过；三会话/两线程定向取消及关闭保护、两个真实Excel预检同时执行且成果不串会话通过，31关联+3调度专项通过。首次完整203+140+411 passed/3 failed（r-0a558709d9f3412588b82a386cf7d6f8）：set_busy忽略显式准备忙碌导致两快捷键/一拖拽回归。修为显式busy或当前任务busy，保留原断言，10关联重测通过。重跑完整203+140+414=757 passed，runner返回ok，证据outputs/nl_acceptance/r-573038b10a194a949d8eea83edeb0dff；限定Ruff及manager/resource Mypy通过。分支parent/fork、未读、后台审核结束批注询问、真实服务并发及Office实例退出仍待验证/实施，不宣称G03/G04验收完成。真实模型累计0元，未打包推送部署，目标active。

- 客户端执行资源限制：新增RA/services/resource_locks.py，固定model容量2、office容量1及输出目录排他，组合资源原子获取、排队可取消、异常finally释放；RemoteSessionClient实际HTTP调用持有model租约，路由/理解/计划/资料识别/审核execute均接入，caller取消不提前释放在途请求名额。资料识别及远程审核将取消令牌传到新cancellable入口；生成入口锁定本轮输出目录，DETAIL子进程从启动到等待退出持有office名额，排队时间不算执行超时。3红后修复测试URL缺/api/v1及两角色错误复用同资料（未改生产校验），新增排队取消不启动Popen及在途caller取消测试通过；23关联通过。完整203+140+411=754 passed，runner返回ok，证据outputs/nl_acceptance/r-20cdd3d0652e451780908da4f5444960。新增/相关限定Ruff及resource Mypy通过；remote_auth_service未修改的_terminate既有BLE001/S110仍在，不称全文件静态通过。限制仅单客户端进程；服务端并发/钱包竞态、跨进程、终止生成子进程后残留Office实例实机验证仍待完成，不能据此开放并发或宣称G04-03完成。真实模型0元，未打包推送部署，目标active。

- 理解/批注生命周期迁移：CompletionEventRelay采用固定两类回调及weakref，注册时绑定owner/project/session/task；理解保留本次外部Skill映射快照，取消/成功回写原会话，后台计划不自动在另一会话执行；批注兼容StepReviewStore但消息写真实底层store，完成后仅原会话可提示下一批注。三项缺入口红灯后23关联通过，追加后台批注失败/取消持久反馈两红后25关联通过。完整200+140+410=750 passed，runner返回ok；证据outputs/nl_acceptance/r-fca5c39619e9402db8509c59be7d0310，限定Ruff及events/manager Mypy通过，无原生崩溃。全局self.worker指针及串行UI门禁仍保留，下一轮改会话级worker查询、关闭时全部取消/等待，并完成模型2/Office1资源锁后开放后台会话；未宣称G03/G04完成。真实模型累计0元，未打包推送部署，目标active。

- 审核事件定向路由：新增task_events.py（固定真实PlatformStore及owner/project/session/task身份、GUI线程QObject relay），审核/组合审核全部信号连接迁入注册入口；输出/完成/失败写原会话，后台进度不覆盖当前会话，释放后的迟到信号丢弃。2红后定向测试通过，但首次连跑出现Windows访问冲突，重复同一13项顺序再次复现，原窗口6项单跑正常。缩小到新增QObject生命周期后，将relay对window/worker改为weakref；随后13项通过且连续3轮各13通过。原生崩溃底层栈未确定，保留失败记录，不称已证明全部Qt问题消失。完整200+140+405=745 passed，runner返回ok，证据outputs/nl_acceptance/r-c82097bfeebd416794d5d3bc271d109d；限定Ruff及manager/events Mypy通过。理解/批注生命周期及资源并发门禁仍未迁移，仍不开放侧栏并发。Docker引擎复查仍缺pipe；真实模型累计0元，未打包推送部署，目标active。下一轮迁移理解/批注worker固定归属，并实现会话定向任务查找及取消，再解除全局worker门禁。

- TaskManager第一步已接真实单任务/组合审核启动入口：新增task_manager.py，冻结owner/project/session/task身份、线程安全注册、同会话重复任务拦截、定向取消；只有匹配worker且线程结束后释放，旧回调不能释放替换任务。新模块缺失红灯及窗口无manager红灯后14专项通过。完整200+140+403=743 passed，runner返回ok，证据outputs/nl_acceptance/r-b6a9cb3fa8b043c19e61386fae7318fe；随后仅整理test_window导入顺序，11专项重测通过，限定Ruff及manager Mypy通过。G03-02仍doing：全局worker兼容入口、理解/批注生命周期、可切换会话的事件路由与资源并发门禁未迁移，不开放侧栏并发，不宣称TaskManager改造完成。下一步绑定输出/完成/失败事件到固定store/session，并迁移其余worker，再开放后台会话。PostgreSQL等待隔离环境；真实模型累计0元，未打包推送部署；旧发布候选清单已因源码变化过期。

- 本轮完整200+140+398=738 passed，runner返回ok；证据outputs/nl_acceptance/r-8a36423cfc7e46fab26a0fc32b6afad0。回归后仅将浏览器探测脚本改为D盘显式profile目录，并重新跑真实Edge通过，证据admin-browser-02（模拟API）。程序及业务模板未改变。PostgreSQL仍等Docker引擎条件，预算硬门禁、任务并发/恢复及浏览器/更新发布主功能仍未完成；真实模型0元，无打包推送部署，目标active。

- 发布清单补齐：明确列出两份管理页面cjs测试、100+20语料及冻结/评分代码、评分CLI、OpenAPI和真实浏览器探测脚本；不放开任意cjs/jsonl或运行观测收集。先缺项1红4绿，修复后6专项通过及限定Ruff通过。完整回归进行中。
- 真实浏览器证据：scripts/probe_admin_billing_browser.cjs使用应用捆绑Playwright和本机Edge（headless、sandbox开启）加载实际管理HTML/JS/CSS，模拟API/合成账号下验证登录、选择、填写、确认仅一次POST、GET回执及退出清空；outputs/nl_acceptance/admin-browser-01/result.json与两张截图，已查看billing-receipt.png，无截断。此为真实浏览器+模拟API，不冒充真实服务/扣款联调。
- PostgreSQL环境：WSL docker不可用；Windows docker.exe报dockerDesktopLinuxEngine管道不存在，未运行引擎；项目环境无Playwright但应用捆绑包可用。已异步请求用户启动Docker Desktop/Linux引擎，未新建付费云资源、未连接生产库。其他工作可继续；真实模型累计0元，无发布部署。

- 本轮完整200+140+397=737 passed，runner返回ok；证据outputs/nl_acceptance/r-4e27bf64f32e4d399908376d1c394546。总控核对表单/API已通过模拟DOM与本地服务测试；下一轮补发布cjs测试白名单、页面实机验证及PostgreSQL并发核对，随后继续累计预算硬边界。没有把UI测试当真实线上验收；真实调用0元，无打包推送部署，目标active。

- 总控费用核对页面：新增待核对选择/分页、冻结编号、总费用/凭证摘要/非秘密引用、确认提交及回执查询。写入结果未知时当前页面禁止盲目重发，使用GET查回执；明确422允许修正输入重新确认。退出清空状态，迟到列表/提交/回执响应按会话丢弃；显示用textContent，不引入本地持久令牌。真实app.js模拟DOM行为测试先缺入口红灯，后补422处理红灯并修复；新核对和原渠道脚本均通过。7页面/API关联及Ruff通过；测试纳入pytest并要求Node.js，非客户端运行依赖。完整回归进行中；尚未做真实浏览器视觉操作验收。发现发布候选收集器只收tests的py文件，必须补本次及既有cjs测试白名单后才能声称可发布。API真实0元，无打包推送部署。

- 本轮完整200+139+397=736 passed，runner返回ok；证据outputs/nl_acceptance/r-5cb8c32e466c452d8d63cf7c250e21a2。管理API权限、输入和幂等已回归；下一轮接总控核对页面（明确总额非追加、提交确认、结果未知先查回执、退出清空），并补页面行为测试。仍未验证真实PostgreSQL并发、预算上限及部署发布链，真实支出0元，未打包推送部署，目标active。

- 管理核对API：新增billing_admin_api并注册到服务端；GET /admin/billing-holds分页列待核对冻结，GET/POST /admin/billing-holds/{hold_id}/reconciliation查询或提交核对。全部要求管理员，提交人固定为当前会话，不接受伪造actor；明细显式白名单，无渠道密钥/请求正文；金额/凭证约束及extra forbid，拒绝输入不回显。2红后7关联通过，补越权/非法金额/凭证/分页边界后9关联通过，Annotated依赖整理后3 API重测通过，限定Ruff/Mypy通过。OpenAPI说明同步；总控UI尚未接，真实PostgreSQL并发/预算门禁尚未验收。完整回归进行中，真实0元，无打包推送部署。

- 本轮修复后完整200+136+397=733 passed，runner返回ok；证据outputs/nl_acceptance/r-7add3192740b4a89867b3d25052d5168。核对服务/模型限定Mypy、相关Ruff通过。新增0004仅本地验证；下一轮接管理员核对查询/提交API、权限/冲突契约及总控页面，并完善已核对后的客户端状态，PostgreSQL并发/备份和累计预算仍须验收。API真实0元，无打包推送部署；目标active，G00—G11未共同验收。

- 本轮首次完整回归未通过：197 passed/1 failed，证据outputs/nl_acceptance/r-4d86b2ef78ae4c6786589478fca3ba73，后续suite未运行。Windows真实句柄测试的sleep替身每次回调都Close并增加released，错误要求仅一次回调；实际第二次暂时占用的外部原因未确定。新增释放后一次WinError32注入，2红2绿稳定复现测试假设缺陷；测试改为只关闭一次、恢复真实等待，继续断言最多3次等待、旧内容保留、最终正确，额外占用必须发生；不修改生产重试上限或业务逻辑。19关联通过，完整回归重跑进行中，首次失败保留。

- 管理员费用核对后端：新增BillingReconciliation及0004_billing_reconciliation增量迁移；独立service核对管理员active角色、非负有限8位金额及凭证SHA256/非秘密引用，按hold锁定，核对总额不得低于此前已知费用。审计/扣款/冻结终态/未知请求终态在同一事务完成；相同凭证金额重放返回原记录，不重复扣款，冲突拒绝；异常rollback。只保留凭证摘要，不替管理员证明上游费用真实。3红后10关联通过，补零费用恢复、已知费用下限及有审计禁止降库后13通过；限定Ruff/Mypy通过，完整回归进行中。管理API/UI与并发PostgreSQL验证尚未接入；不可作为已上线闭环。真实0元，无打包推送部署。

- 本轮完整198+130+397=725 passed，runner返回ok；证据outputs/nl_acceptance/r-d1d14216f3844a918061bced74efed3f。回归后仅整理import及lambda空字典构造，限定Ruff通过、25关联再次通过；Mypy缺pywin32类型存根仍如实保留。客户端专用费用待核对提示已接通。下一轮应实现管理员核对审计表/迁移及原子幂等结算，随后接管理API/UI与预算保护，不能再把此缺口只作为状态说明。真实调用0元，未打包推送部署；目标active。

- 客户端费用待核对提示：RemoteSessionClient按专用code抛出BillingReconciliationRequired，使用本地固定文案，不回显服务端原消息；Routing/UnderstandingWorker保留专用提示；持久任务诊断按准确异常类型识别，不混为网络错误。3红后25关联通过；完整回归进行中。Ruff发现2处格式问题待回归结束整理，限定Mypy受既有pywintypes/win32cred缺类型存根阻挡，未忽略错误。管理员核对入口需新增独立审计表及增量迁移，当前尚未实现，不能解除真实账号冻结或宣称费用闭环。真实0元，无打包推送部署。

- 本轮完整198+130+394=722 passed，runner返回ok，证据outputs/nl_acceptance/r-ec38742f001a43a1a0564c581029253d。未知费用暂停及冻结保留已验证；下一轮补管理员核对结算（需证据、审计和幂等）、客户端专用提示，再接预算及并发恢复。不能将本地中间状态部署为完成版，回退旧服务对uncertain不兼容需门禁。真实0元，无打包/推送/部署；总目标active。

- 未知费用状态：新增BillingReconciliationRequired；四类无可信usage错误（usage_invalid/missing、network_error、invalid_json）将BillingRequest及BalanceHold置uncertain，保留前序已知费用、不结算/释放、不换渠道；原请求重放及新预占/已有冻结执行被阻止，过期清理不释放uncertain。审核任务保留专用错误并跳过capture，重试不再提示创建新任务。首次测试导入错误已纠正，5业务红灯后25关联通过；追加预占ID复用1红后封堵，26关联通过，限定Ruff/Mypy通过。完整回归进行中。状态使用既有String(16)字段，无迁移；尚需管理员有证据的核对结算入口、进程崩溃/并发边界、HTTP不确定响应分类和累计预算门禁，不能上线宣布计费闭环。真实支出0元，无发布部署。

- 本轮完整198+124+394=716 passed，runner返回ok，证据outputs/nl_acceptance/r-fdbd005e7dad4f208a585efc0b580d0e。用量严格校验已回归；下一轮处理未知费用状态及冻结资金不被提前释放，再接累计预算门禁。保留已知Starlette/httpx弃用警告，不称无警告。真实模型0元，未打包、推送、部署，目标active。

- 用量可信度修复：provider_gateway原先把空usage/非法字段归零、分项超总数用max截平。新增最小负测16红1绿后，强制非负整数、必需输入/输出总数、分项不超总数、可选total核对及reasoning重复字段一致；非法/缺失用量的成功响应抛出不可自动重试错误，不返回零用量成功。不改变供应商价格或客户倍率。补边界后27关联通过、限定Ruff/Mypy通过；完整回归进行中。参考DeepSeek官方chat-completion usage契约：https://api-docs.deepseek.com/api/create-chat-completion/ 。当前仅修复用量入口，MeteredModelService对未知费用仍按失败流程处理，费用待核对/预算上限/持久恢复未完成，不能发起20元真实验收；累计0元，无发布部署。

- 本轮完整回归198+104+394=696 passed，runner返回ok；证据outputs/nl_acceptance/r-c30a9f7b434d44e3ba5b7e5071f8bace，限定Mypy五文件通过。冻结语料入口可复核，G02-05/NL07-01/NL07-02仍doing，不能以离线测试代替真实模型语义验收。下一步优先完成付费验收预算硬边界和真实响应来源链；浏览器目标能力、并发Harness及发布更新链仍未完成。真实累计0元，未打包、推送、部署，目标active。

- 恢复核验：上一轮JUnit实际证据为outputs/nl_acceptance/r-8e6e17e20bbc49af828a3a7db7b3763b，198+104+393=695 passed，三组errors/failures/skipped均0；进程句柄已失效，依据落盘报告确认，不将runner单测的synthetic报告当完整回归。语义语料仍未真实模型验收。
- 本轮评分入口增加--frozen-corpus，与自定义--cases互斥；正式模式调用冻结校验，并要求展开代码与仓库可信版本一致，不执行输入目录中的代码；报告标记frozen_corpus_verified及manifest哈希。先1红后9专项通过、限定Ruff通过。完整回归待记录。真实模型尚未调用：现有预占是估算金额，不能仅靠调用后查余额保证20元累计上限，需完成预算门禁后再收费验收；无发布部署。

- 语义语料1.0.0：五类基础各20条，共100条，另有单独留出改写20条。corpus.py展开合成文件ID/版本、前文及明确标签/人工检查项，冻结清单记录六个JSONL及展开代码SHA256；重复输入/ID和冻结后改动拒绝。浏览器/OA目标态例保留browser.interact预留标识，当前契约缺口不通过改标签或删分母掩盖。CLI已兼容精简格式并记录展开代码哈希，空观测120条全失败；数量覆盖不等于语义通过。初始用例载入/CLI红灯后8专项通过，限定Ruff通过；正式真实响应采集、留出重复稳定性及人工复核未做。完整回归待记录；API0元，无发布部署。

- 本轮完整198+104+390=692 passed，三份JUnit门禁ok，证据outputs/nl_acceptance/r-b5b15f3e148f4345845f3e7fb83ec01c；限定Ruff通过。评分器/CLI的Mypy首次仅作为repo外模块检查时报import-untyped；显式加入共享契约及project_catalog源码后4文件通过，未用忽略类型来掩盖。下一轮整理正式100条基础与独立留出集，并接实际响应采集/复核；当前只有评分基础，真实语义正确率未知。API累计0元，未打包推送部署，总目标active。

- 澄清修复完整198+104+385=687 passed，证据outputs/nl_acceptance/r-2842dd1668c24aa5bde3ebfbe70ec16b；agent_contracts/agent_controller限定Mypy通过。原始限制不会被2000字/轮次截断，超界需用户完整重述，不自动遗忘授权边界。
- 自然语言验收基础：新增tests/agent_acceptance/scoring.py和离线scripts/evaluate_agent_semantics.py。按意图/动作/目标/参考/排除/Skill/追问字段评分，缺观测失败、重复/越界拒绝；基础/留出分别统计，安全100%、整体/分类/每个split至少95%及100+20覆盖门禁。报告始终release_accepted=false，并列真实来源、重复稳定性、人工语义证据及端到端副作用未验；命令不联网、不覆盖证据、不输出原响应。TDD核心3红、命令1红、独立留出门禁1红后5专项通过。正式100条及独立留出语料尚未整理，不能将单测构造标签算作该要求完成。完整回归待记录；API累计0元，无发布部署。

- 多轮澄清安全修复：复现用户要求/模型追问超过2000字时截断末尾，以及轮次增加时静默丢弃旧约束，3失败测试确认。MessageRef上限与12000字当前要求一致；AgentController保留全文且不截去早期消息，持久化追问前验证下一轮10消息/64KB限制，超过上限明确提示新会话完整重述，不改现有状态或执行业务。29项控制器/会话/服务端关联通过，限定Ruff通过，完整回归待记录。未调用真实模型，API累计0元，未发布部署。

- 本轮完整198+104+382=684 passed，runner三JUnit门禁ok；证据outputs/nl_acceptance/r-befe73347bf441b08fecd784bb107401。相关Ruff、compound_task限定Mypy通过；批注/外部规则组合对话链已有合成业务验证，未进行真实模型语义验收。下一轮优先自然语言基础/独立留出验收集及跨轮指代缺口，再继续未完成Harness/并发/浏览器/更新发布门禁。总目标仍active，累计API0元，未打包、推送、部署。

- 批注轮完整198+104+376=678 passed，三JUnit门禁通过，证据outputs/nl_acceptance/r-04245c80e9a74145840a26ebed8d2aa2；harness/review_delivery限定Mypy通过。组合批注允许/拒绝以及单步骤compound已接入，不是Office/WPS全矩阵或线上验收。
- 外部Skill组合绑定：按当前账号加载唯一已启用且完整/依赖满足的包，将id/version/SHA256和合并规则绑定到每步配置；执行前重编译比对，停用/换版本/规则或指纹篡改均不启动本地生成。未结束组合任务阻止包切换；确认页显示包身份/指纹，管理页纠正旧的“尚未接入”说明，不授予脚本或原件修改权限。4红后12关联通过，补绑定篡改及管理UI后16通过；对话自然语言入口→真实生成→模拟外部审核→报告链接6项专项通过。静态检查通过，完整回归待记录；付费0元，未发布部署。

- 组合批注补齐：按审核步骤主动询问并持久记录已询问；拒绝不写副本，主动点击入口也计为已处理询问；顺序处理多审核步骤，取消/错误不自动弹出后续批注。复用ScopedReviewStore及现有保真批注器，只读取该步文件，输出及链接留在对话，不改StepResults/检查点。专项1红4绿后实现，确认允许/拒绝及真实副本生成；另复现单步骤compound被旧结果展开逻辑破坏路径，1红后仅对compound保留plan封装。关联30 passed；限定静态检查及完整回归待记录。模型仍模拟，真实累计0元，未发布部署。

- 本轮完整198+104+372=674 passed，runner三JUnit门禁返回ok，证据outputs/nl_acceptance/r-5d7dfe16f5e541c1a9ca48973af58744；新增review_delivery限定Mypy、相关文件Ruff通过。组合步骤标准Word导出已接客户端并验证，下一轮继续逐步骤批注主动询问/副本交付及单步骤compound结果兼容。真实API累计0元，无打包、推送、部署；G00—G11目标保持active，尚未共同验收。

- PDF预检门禁修复后23项专项及限定Ruff通过；专项首次漏设basetemp导致2项在C盘触发业务目录保护，改为D盘后通过，未放宽保护。完整198+104+369=671 passed，证据outputs/nl_acceptance/r-f63e7938b88046128894a4e2b3cd2b0f，回归runner返回ok。
- 组合审核导出：新增review_delivery只读范围视图，从已完成步骤检查点解析准确文件/生成成果，导出元数据单独存review_deliveries，不修改不可变StepResults或计划检查点。客户端增加逐步骤标准Word导出和打开链接，保存位置仍由用户选择且禁止系统盘。2红后核心2绿、UI入口1红后8关联通过；组合批注自动询问/执行尚未接入。完整回归待记录；API累计0元，未发布部署。

- UI组合入口完整回归已核实198+104+367=669 passed，三份JUnit均无失败/错误，证据outputs/nl_acceptance/r-ba7db45c468241a0adf0fc3bf66bf090；app.py限定Ruff通过。未打包、推送或部署，真实API累计0元。
- PDF预检编译门禁复现：针对review.preflight/report.review对照测试，1 failed/14 passed，确认通用编译器误把审核专用PDF参考限制施加于本地可读性预检；只收窄这一条件，不放开正式审核PDF目标。修复后验证待记录。

- 本轮UI组合入口：UnderstandingWorker在完整组合/参考请求后调用提案接口并验证；routing_finished不再直接拒绝，而是构造compound快照、纯文本可滚动确认、绑定receipt并启动TaskWorker(client)。固定项目store，确认前后校验账号/会话/模型及理解完成后的准确修订；取消/过期不创建业务任务。对话展示分步骤反馈和成果链接；plan_results重验步骤结果归属/检查点，打开文件核对目录和哈希。完成多步骤可只读核对恢复为succeeded，不重跑。
- TDD UI2红后5 passed；补恢复1红后实现，修订关闭+1门禁误用在专项发现并纠正；取消迟到、模型/修订变更、成果会话/哈希、纯文本确认及原UI合计16 passed，新模块限定Ruff/Mypy通过。UI模型理解/提案为mock，工商生成及解析真实；组合审核的标准报告导出/批注后续动作、外部包组合绑定仍待完成。完整回归进行中；实际模型0元，无发布部署。

- 本轮完整198+104+360=662 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-981a2c92d4044b7bb3a8c70664321b57。组合TaskSpec及正式执行入口通过；下一轮接UI提案/确认、成果交付与已完成多步骤恢复。外部包组合绑定和真实模型验收仍未完成；API累计0元，无发布部署。

- 本轮compound_task：构造TaskSpec v2组合快照，将PlanningRequest/PlanProposal、精确范围/版本/修订、每步本地规则和输入配置绑定；执行前重新编译比对，不能靠授权receipt放过被伪造的权限/配置。execute_task已分派compound到真实Harness，按步骤创建独立审核/资料识别provider；有模型步骤却未登录时，在任何本地生成前拒绝。工商唯一来源自动映射，detail沿用自动识别；外部Skill组合规则绑定尚未实现则明确拒绝，不替换为内置规则。初始5红后执行关联28 passed，补真实生成+模拟审核/缺登录/缺receipt后8 passed，限定Ruff/Mypy通过。完整回归进行中；UI提案确认/组合成果展示未接，模型测试均mock、真实累计0元，无发布部署。

- 本轮完整198+104+352=654 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-12afa4aa67b440c8b2b3b342f5c991e9。真实双生成目录隔离与跨步骤成果拒绝已验；下一轮推进compound TaskSpec构造、统一执行入口和UI确认/交付。尚非自然语言组合业务验收，真实API0元，无打包推送部署。

- 本轮多生成步骤：generation_paths以任务ID和步骤哈希隔离目录，拒绝跳转/重定向/已有步骤目录复用；旧单步骤路径保持兼容。GenerationAdapter在compound模式核对注册计划、step_configs、输入引用/角色和规则哈希；每步独立配置/目录，资料识别幂等ID加入步骤哈希。artifact_registry按生产步骤目录验收，拒绝冒用另一步成果。真实双工商生成后只读检查第二步：1红后通过；跨步骤错投负测、路径/适配器专项15 passed，生成验收关联15 passed，限定Ruff/Mypy通过。完整回归运行中。compound TaskSpec构造及UI仍未接入，不是用户自然语言组合验收；API累计0元，无打包发布部署。

- 取消门禁修复后专项12 passed；完整198+104+345=647 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-92665e1db4fe4e35b25e275f6fe036b4。首次失败证据保留。下一轮继续组合TaskSpec与UI提案确认/执行入口，生成步骤目录隔离仍须完成；不将本轮参考语义视为完整多Skill验收。真实API0元，无打包/推送/部署。

- 首次完整回归198+104通过，平台344 passed/1 failed；证据outputs/nl_acceptance/r-eeae7d389e0341cca97a7c8650b15031。test_cancel_before_read_does_not_extract揭示新增参考范围校验早于取消检查，已取消且未完整解析的输入触发KeyError。将取消门禁前移到字段读取之前，保留领取/终态规则；不修改测试来掩盖回归。修复后专项和完整重跑待记录。

- 本轮步骤范围语义：组合理解不再强制每份资料适用每个Skill，先验证至少一个所选能力可接，实际分配由compiler逐步复核。ReviewAdapter传本步goal/constraints及reference_inputs；preflight先过滤原角色的隐藏/依赖污染片段，再标记参考，仅向目标文件交付流式和最终意见。纯参考审核/越界参考ID在模型调用前拒绝；参考及排除范围外模型意见明确显示警告。TDD 2红6绿后关联37 passed，补隐藏依赖/旧文件输出及纯参考门禁后专项10 passed，限定Ruff/Mypy通过。完整回归进行中；自然语言组合UI入口仍待接，真实API累计0元，无发布部署。

- 本轮完整198+104+340=642 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-159575168d074418ba6706d266f49bb3。新模块/测试限定Ruff与Mypy通过（补测后仅整理import）。接口和客户端封装尚未进入UI组合执行；下一轮处理按步骤格式校验、业务参考角色和提案入口。真实模型支出0元，无发布部署。

- 本轮服务端/客户端提案链：新增PlanningRequest与共享validate_proposal、POST /api/v1/agent/plan及task_planning能力；只传受限理解上下文，使用plan:<request_id>复用既有MeteredModelService的幂等/计费，不执行业务。请求再次验证后才调用模型，返回计划校验范围、角色、依赖/无环、重复/遗漏及64KB限制。客户端预检能力、认证POST、取消前后检查和二次范围校验；本地compiler也调用共享验证。服务端7红后19关联通过，补负测12 passed；客户端5红后21关联通过。新模块限定Mypy通过；旧api/remote_auth文件有既有lint债务，不称全库静态绿灯。完整回归进行中，UI自动请求提案及组合执行仍待接入；真实API累计0元，无部署。

- 本轮完整193+92+340=625 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-d93c8a9e53bb43cbad7a38eca801b808。组合提案编译核心及旧计划缺省字段兼容通过；下一步接服务端结构化提案及业务步骤参数/参考角色，不把本轮核心测试视为UI组合任务完成。真实模型0元，未发布部署。

- 本轮组合计划编译：独立PlanProposal协议只接受步骤目标/Skill/输入角色/依赖，不接受模型代码或授权。compile_proposal绑定理解请求、覆盖全部所选范围、保留约束/文件角色；本地映射工具版本/规则hash，提前验证格式和生产成果类型。初始11红后20 passed，追加旧计划兼容/格式/成果类型3红后修复，相关31 passed，限定Ruff/Mypy通过。完整回归运行中；尚未接服务端提案与UI，不能称自然语言多Skill验收完成。真实API累计0元，无打包推送部署。

- 本轮完整193+92+326=611 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-7dfb9533fb8e451e967624e3350553cb。完成生成成果到只读消费步骤的受控传递；下一轮继续自然语言组合计划编译与真实入口整合。未打包/推送/部署，真实API累计0元。

- 新增artifact_registry：只解析已注册计划的输入；生成成果必须来自成功的祖先步骤、匹配步骤结果引用/哈希，且位于本任务输出目录。真实GenerationAdapter生成合成工商Word后，ReviewAdapter仅解析该成果，不将成果加入全局历史附件。篡改成果、未完成生产步骤、伪造消费步骤及跨账号均拒绝；原输入哈希不变。初始2红1绿后实现，关联32 passed，补强门禁4 passed，限定Ruff/Mypy通过。完整回归正在进行；不将手工构造DAG测试冒充自然语言组合任务验收。真实API累计0元，无发布部署。

- 修复后完整193+92+322=607 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-99816db4e68b4e12a4e20bccaf850751。生成单步骤现已进入Harness，迁移容错负测通过；首次失败证据保留。下一步是自然语言组合计划、步骤产物互传及实际多Skill验收，不将单任务整合当作全目标完成。真实API累计0元，未打包/推送/部署。

- 本轮首次完整回归未通过：193+92通过，平台317 passed/1 failed，证据outputs/nl_acceptance/r-17b8126281b5433da756a913a03cc73c。失败在test_live_data_lease_blocks_migration_even_with_closed_claim的stage.rename(destination)，WinError 5；不能归因为生成适配器，也未确定占用进程/ACL原因。未将此轮记为全绿。
- 对该明确失败边界补错误注入复现：临时/持续Windows拒绝重命名2红后，在storage_migration加入4次有界重试（仅WinError 5/32/33），重试前核对源/临时目录清单和目标不被替换；持续失败保留源与旧偏好、保留失败stage供诊断。再补重试间目标冲突/暂存变更拦截，迁移15 passed，定向Ruff通过。此为已知拒绝访问类故障的容错，不宣称已确定原外部占用者；修复后完整回归运行中。

- 生成类单步骤入口已与只读审核统一经过Harness：新增GenerationAdapter，execute_generation支持调度器管理状态且默认保留旧直接调用行为。核对授权、版本/规则、输入集合、模型模式；使用现有锁定模板/子进程/原件哈希门禁，不修改模板。诊断性失败结果按StepResults保存并还原旧UI反馈，不把资料不足当作成功。
- 生成成果二次检查主文件存在、限定任务output目录、真实文件名/后缀/哈希；失败只允许user_feedback.md，不交付业务成果。取消不发布成果引用。当前生成适配器明确仅支持现有execute步骤和单任务目录，尚未开放多个生成步骤或产物互传；组合计划仍未验收。
- TDD真实工商生成入口结果记录1红；统一后专项16 passed（一次命令误列不存在test_generation_cancel.py退出4无测试，已更正为现有task_cancellation.py，不计通过）。新增成果负例2红2绿，修复文件名伪装/失败夹带后生成/版本门禁/执行40 passed；限定3模块Mypy、Ruff通过。完整回归运行中，真实API消费0元，未发布部署。

- 本轮完整193+92+314=599 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-c1b756f73c004f7f9e657001ee682865。客户端只读审核已进入Harness并保持原结果界面行为；下一轮推进生成适配器和组合计划。真实API消费0元，未发布部署。

- 客户端只读预检/审核入口execute_task已转至真实ReviewAdapter + 顺序Harness；保留入口身份/范围/规则/授权/记忆门禁，内部已领取桥接避免再次领取。单步骤结果从StepResults恢复为旧review/preflight格式，原对话、批注/导出接口不要求改成plan格式；生成入口仍暂留旧路径，下一轮接入。
- 模型调用ID按run+step固定；适配器使用本次刷新后的记忆上下文，不复用已撤回记忆。SourceValidationError明确归属validation阶段；超时/连接异常保留unknown步骤及interrupted任务，向UI失败通道抛出，不返回审核完成，不重新调用。事件只记异常类别，不保存异常正文。
- TDD原入口缺步骤结果1红后接入，执行/窗口/适配器/调度43 passed；补超时/连接异常与窗口结果持久化断言，执行/窗口/批注/导出39 passed。限定3模块Mypy及Ruff通过；完整回归运行中。真实API消费0元，未打包/推送/部署。

- 本轮完整193+92+312=597 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-8455cd8e76ac40539e31d5d0b9bde048。已更新本地TaskSpec/DB版本兼容说明；下一步接客户端调度入口及生成适配器，仍不宣称真实模型/多Skill全链验收。真实API累计0元，未发布部署。

- 真实只读适配器adapters/review.py已接现有preflight解析/PrivacyChunkSelector/哈希门禁；skills.preflight增加由调度器管理状态的模式，旧入口默认行为保持。适配器核对已授权文件记录、模型/规则哈希及动作，模型幂等ID按run+step固定，不接收任意路径；未解析的产物引用明确拒绝，待类型化产物流完成。
- schema 4新增execution_results；StepResults按账号/run/step隔离、哈希校验、同结果幂等且不可覆盖，结果正文留本地DB，事件/checkpoint仅保存引用。finish_step拒绝不存在、跨步骤或损坏的结果引用。旧库升级前备份，新库初始化全结构。
- TDD真实适配器/迁移4红后与原执行链39 passed；补伪造引用1红后门禁修复，增加源文件变化、不发布结果、结果损坏和不可覆盖，适配器/调度/事件/迁移35 passed，限定Mypy和Ruff通过。真实解析器完成两步合成文件顺序测试；模型端仍mock（过滤与幂等已测），没有收费。当前UI仍旧执行入口，生成及UI整合尚未完成，完整回归运行中。

- 本轮完整193+92+305=590 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-7eaa55b9e2764418ab81aeca1979d79f。调度核心合成验证完成，下一步将真实业务执行器拆成typed适配器并接入，不把mock计为实际多Skill验收；真实API累计0元，无发布部署。

- 顺序DAG调度核心新增harness.py、tool_dispatcher.py：仅执行应用代码注册且工具契约存在的适配器；整计划预检适配器可用性，按依赖顺序领取，每步前及整体完成前复查持久授权，校验typed ToolOutcome的步骤归属和全部门禁。event_store.finish_step原子写步骤状态、结果引用/门禁元数据及事件，不重复写业务正文；同一token同一结果幂等。
- 失败、无效结果、取消阻断后续步骤；超时等不确定异常记录unknown/interrupted并要求核对，不抢占、不自动重跑。新调度器目前通过合成适配器测试，尚未替换客户端真实业务入口，真实审核/生成适配器、产物类型绑定及续执行仍待接入；不得据此宣称组合业务验收完成。
- TDD新调度6红后核心10 passed，补超时/缺门禁/取消迟到及启动前取消后与事件/恢复17 passed。限定Mypy与Ruff通过；完整回归运行中。真实API累计0元，无打包、推送或云端部署。

- 本轮完整193+92+295=580 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-4648a5926ef04beab34cb0966592afd4。TaskSpec v2/旧记录去授权已验证；接下来推进多步骤工具结果与调度，不把单适配器路径当作组合任务完成。真实API累计0元；没有打包、GitHub发布或Zeabur部署。

- TaskSpec v2已成为build_task_spec的新任务格式；任务身份/计划协议仍独立保持schema 1。store兼容保存v1/v2历史，read_snapshot对v0/v1清除执行权限并标记需重新确认；execute_task仅接受v2，PermissionService拒绝为v1签发新授权。v2无论是否保留requires_authorization标记都必须核对持久receipt，计划/文件范围缺失时拒绝执行。
- TDD：v2生成/v1只读历史/v1禁止执行3红4绿后实现，初轮45 passed；补缺计划/范围2红后修复，加入v1禁止补授权和删标记不可绕过，任务/权限/执行/生成/窗口50 passed。测试fixture显式签发合成授权以覆盖原有规则及业务门禁，未放松原有断言。限定Mypy发现snapshot_identity可空类型，改model_validate保留运行时严格校验后3模块通过；Ruff通过。完整回归运行中，待追加。

- 本轮完整193+92+289=574 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-fc18e83fce0544dbaef5f5e82dbf4dbc。下一步推进TaskSpec v2、历史任务不得恢复旧授权，以及通用步骤调度/适配器；整阶段仍未验收。真实API累计0元，客户端EXE/GitHub/Zeabur均未发布本轮变更。

- 本轮授权绑定：schema 3新增execution_authorizations，仅保存绑定哈希、确认ID、时间、撤回标记。PermissionService绑定完整初始快照（仅排除执行时记忆上下文）与实际输出根目录；核对确认快照、拒绝原件修改、不可改写/复用已撤回凭据。目录搬移、文件/模型/任务/动作改变使授权失效。
- 新UI任务在既有审核范围/生成副本确认后保存receipt，execute_task在规划及进入工具前二次核对；缺失/撤回/被替换的授权阻止工具调用，删除required标记不能绕过已有receipt。当前历史v1兼容执行路径尚保留；TaskSpec v2和历史仅显示策略、按步骤细粒度授权、批注/浏览器等动作仍待后续，不能称通用权限系统完成。
- TDD：权限7项先红后绿，v2→v3迁移1红后绿；补迁移回滚、输出目录搬移和撤回/越权负例，权限/迁移/真实窗口/执行专项46 passed。TaskWorker持有可切换ProjectCatalog另1红，改为构造时固定PlatformStore后1 passed，避免后续项目切换串库。限定Mypy及Ruff通过；完整回归运行中。真实模型支出0元，无发布/部署。

- 本轮完整193+92+277=562 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-91750fb236084e738c8687880bbfd7ba。下一轮继续授权绑定与通用步骤调度，不能把现有单步骤终态恢复视为多步骤执行已完成。未产生付费模型调用、发布或云端修改。

- 步骤持久化已接真实execute_task：计划注册匹配原任务身份/快照且不可替换，原子领取只允许pending且依赖满足，running不自动抢占；步骤与顺序事件同事务写入，终态仅从现有单适配器执行结果取得，checkpoint只存结果引用。事件读取按owner和游标隔离，不包含领取令牌/业务正文。
- task_recovery及会话打开入口已接单步骤终态缺口修复；运行中/多步骤状态不明只提示需核对，不判定进程死亡、不调用工具、不重发模型。完整远端查询、租约与通用多步骤调度仍未完成，不能把本轮记为整个Harness验收。
- TDD：初始事件存储/真实执行5红14绿；实现后领取/执行21 passed，补失败/取消/模拟SystemExit中断后22 passed。终态恢复3红后绿，会话恢复入口1红后绿；联合25 passed，会话/恢复/事件12 passed。新存储/恢复/执行3模块限定Mypy及修改源文件Ruff通过。完整回归运行中，待追加证据；真实API支出仍0元，无发布部署。

- 持久执行结构首轮：local_migrations schema 2新增execution_plans/steps/events，步骤状态含unknown，事件按run序号及去重键唯一，关联约束保留；当前仅结构，尚未连接真实调度器或实现恢复，不能声称崩溃恢复完成。升级按实际旧版本命名备份、事务回滚，已有活动任务仍阻止迁移，新项目直接初始化全部结构。
- TDD新增3项先失败（旧版不升级、无v2迁移、无事件表），实现后迁移/存储/领取专项21 passed；完整193+92+266=551 passed，三份JUnit门禁通过，证据outputs/nl_acceptance/r-5914aa63e749482e9616cff07c50b30d。随后仅整理import格式，定向Ruff通过。下一步接步骤原子领取、事件写入、执行及保守恢复。真实API累计0元，未发布、未部署；本轮不记录用户提供的凭据。

- 本轮完整193+92+263=548 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-3358ff84de3f4e69a80d0fe3278db4f6。新计划/工具/编译器3模块限定Mypy通过。仍是计划校验与旧执行器集成，不是多步骤恢复/并发/通用授权完成；下一步继续持久Harness闭环。真实API消耗仍0元，无发布部署。

- 计划/工具约束首轮：tool_contracts.py声明当前四个真实适配器的副作用、网络、资源类别、取消边界、重试策略和结果类型；不开放shell或模型自定义执行器。execution_plan.py固定任务身份、输入哈希、工具/Skill/规则版本、步骤依赖和输出引用，拒绝未知工具/版本、跨身份、循环、范围外输入、无依赖输出引用。
- planner.single_adapter_plan已接build_task_spec；execute_task在文件解析/模型调用前重建预期计划并比较，不仅校验JSON形状。当前已有单适配器任务可执行；多步骤结构虽可校验，尚不能在旧执行入口运行，等待后续durable Harness，未把复杂任务扁平化。旧无execution_plan的v1记录仍走原身份/文件/权限门禁。
- TDD：计划/任务快照/执行入口初始10 failed、17 passed；实现后专项27 passed，定向Ruff通过。另补依赖产物顺序及合法形状但规则哈希被替换的负面用例，完整回归正在运行。未改模板/原件，未执行真实模型或远端发布。

- 本轮完整193+92+252=537 passed，三份JUnit门禁通过；证据outputs/nl_acceptance/r-c1dac46840584d55a8a2bab2b91be89c。能力契约与输入格式追问已进真实理解链；接下来继续计划/Harness的工具契约、执行依赖与权限绑定，不能将本轮候选目录当作整个G02/G03完成。没有付费模型、发布或云端变更。

- Skill能力目录接入：skill_contracts.py + builtin_contracts四个JSON声明真实输入格式/角色、可选资料、输出、后置门禁、后续动作及环境边界；版本与BUILTINS强校验。capability_registry把受控摘要传给理解模型，锁定模板缺失/变化的生成器不广告为可规划能力；不声称Office或资料真实性已验证。未修改业务Skill规则、锁定模板及链接。
- 真实差异明确列示：明细表自动识别至生成链当前使用XLSX，余额表可选但轻量证据仍必须满足；工商沿革平台适配器仅Excel，未把原Skill PDF整理能力当作已接入；PDF报告审核仅参考。understanding_policy已接Controller，格式不支持时转追问并清空拟执行Skill，不擅自转换或降级。
- TDD：契约/目录/Controller先5红4绿，实现后9 passed；打包与导出资源先2红4绿，补PyInstaller add-data及白名单后与UI合计9 passed；格式策略先5红，实现并接Controller后13 passed。定向Ruff通过。完整回归运行中，待追加；新资源仅配置了正式打包入口，尚未生成正式EXE。

- 修复后完整回归193+92+243=528 passed，且三份JUnit完整性门禁通过；证据outputs/nl_acceptance/r-a9eebff8aad34b998e4b413dba51219d。定向Ruff通过。新聊天理解入口本地mock验证完成，真实服务端尚未部署，组合规划、引用角色执行及完整多轮语义验收仍待后续；没有付费调用或远端写入。

- 真实聊天入口已改接UnderstandingWorker + 无Qt AgentController，不再要求所有消息先选附件。控制器持久化未决问题的有限用户/助手上下文，只在追问续接时带入；新的理解任务/取消使迟到结果失效。服务端返回后再次核对文件记录，单Skill目标集合直接传execute_plan，不重复写用户消息。复合Skill或独立参考处理尚未接通Harness时明确未执行，不降级为单任务；对应G03仍待实施。
- 控制器/UI初始4红1绿后实现，专项16 passed。发现ProjectCatalog会切换active库，追加真实两项目切换红灯；控制器固定发起时PlatformStore，复测8 passed。新模块Ruff通过；原件/模板未变，未发真实模型请求。
- 首次完整回归r-863f7cd395384477b5eed613e1fef26d为中断无效证据：旧test_empty_project_cannot_start_run无登录模拟，删除附件拦截后打开模态登录窗口停住；定向终止本轮pytest子进程PID7692（已核对其唯一run路径）。WMI调用执行终止后返回整数，又被调用导致TypeError；子进程退出0使原入口误打印ok，但technical_platform.xml缺失，绝不计为通过。修改旧用例模拟取消连接，保留无业务任务/无历史污染/输入保留断言；直接平台242 passed。
- 因此补强回归入口：零退出码仍必须有完整JUnit、有实际testcase且无失败/错误，缺失返回125。先1红3绿，修复后4 passed；当前重新运行三套完整回归，待追加结果。此为验收工具修复，不将中断日志视为完成证据。

- 本轮完整193+92+236=521 passed，证据outputs/nl_acceptance/r-20bfbcf0d662467998a791e2626fc5b1；没有真实模型扣费、GitHub推送或云端变更。下一步接入不依赖Qt的AgentController与真实聊天入口，不能停留于未使用的新接口。

- 自然语言理解协议首轮：共享agent_contracts.py与客户端转出口定义版本化意图/目标/三类文件范围/约束/交付/缺项/消息依据/候选Skill/下一步动作；严格字段和大小限制，不含权限字段。新增服务端POST /api/v1/agent/understand及提示词，复用鉴权/计费；未知引用、角色重叠、伪造Skill/消息、矛盾动作全部拒绝。服务端仅理解，不调用业务执行器。旧skill-route保持原行为。
- 客户端RemoteSessionClient.understand_task新增能力预检、取消前后门禁和共享协议二次校验。尚未替换聊天窗口旧RoutingWorker，controller、多轮澄清、计划执行和100条真实语义评测仍待完成；不可将协议mock测试称为自然语言效果验收。
- TDD：服务端11项红灯后实现17项新旧路由专项通过，增加真实鉴权路由mock后新接口12项通过；客户端2项缺方法红灯后发现测试遗漏/api/v1前缀，修正fixture，原12项与新增2项通过，再补2项预检取消测试。共享契约Mypy与新模块定向Ruff通过。Dockerfile明确复制共享模块，导出白名单包含该模块和提示词，导出5项通过；Zeabur现存Dockerfile覆盖尚未修改，部署前必须同步。

- 本轮完整回归189+80+236=505 passed；证据outputs/nl_acceptance/r-d034d308a1924bf19a4701fe085d3145。任务文件范围模块已进入真实快照及执行校验，语义理解与交互接入未完成。未推送、未部署、真实模型累计0元，目标继续active。

- 文件范围地基：新增file_scope.py，目标/参考/排除互斥，绑定owner/project/session/revision及文件ID/哈希；TaskSpec创建和执行前均接入当前目标范围核对。reference_resolver.py仅对可信候选ID集合做精确名称/ID/哈希匹配，同名返回歧义候选、不猜最新版本，不接受模型路径、不读取文件。旧无file_scope的v1快照继续走原有归属/selected_files/权限门禁。
- 本轮TDD：9项缺模块失败后基础解析通过；TaskSpec集成1项红灯、执行入口4项越界快照红灯后修复。专项27 passed，新增模块/任务快照及对应测试定向Ruff通过。自然语言理解服务、上传批次、跨轮指代和澄清UI仍未接入，不标G02整体完成；完整回归正在运行，待结果后追加证据。

- 外部Skill兼容信息接入版本面板：SkillInstallation.release_inventory按当前owner读取并重新校验归档哈希、格式、适配器和依赖，区分disabled/dependencies_missing/enabled_compatible/unavailable_or_changed；不显示说明正文、不自动启用，兼容不代表任务授权。local_release(store=...)读取失败标无法确认，不把损坏当空清单。
- TDD：安装清单2项缺方法红灯、版本入口1项红灯，实现后专项19 passed；复查发现版本检查构造安装管理器会创建表，追加1项只读测试红灯后增加initialize=False，仅安装管理入口保留初始化。最终版本/安装18 passed，定向Ruff通过；完整189+80+223=492 passed，证据outputs/nl_acceptance/r-2b3fd510dada4a04bc2c6ecac8abb397。没有外部发布或真实扣费。
- 线上构建记录只读补查：当前部署构建日志显示OCI层上传成功与build completed，但可见记录未给出完整镜像摘要；不将短blob标识冒充镜像SHA。G00-01仍保留此缺口，未重启或重新部署。

- 发布候选清单落盘：outputs/nl_acceptance/source-candidates-20260916-g00.json，303项相对路径/大小/SHA256/git blob SHA1，无文件正文；状态candidate_not_release_approved。导出器只允许写outputs/nl_acceptance内不存在的目标，拒绝路径重定向和覆盖。2项新测试先失败，实现后5项专项通过，Ruff通过。该清单是生成时检查点，后续账本/源码修改会改变哈希，最终发布须重新生成并完成内容安全审查。
- 本轮完整189+80+219=488 passed，证据outputs/nl_acceptance/r-f0da7d9fb50e4bdc9042b6ba4c931952。G00-02签收仅代表显式候选同步清单与脏工作区保护，不代表303项内容均可公开或获准立即发布；未执行提交、推送、部署或真实模型调用。

- 本轮完整189+80+217=486 passed；证据outputs/nl_acceptance/r-bb9af72fc6f3447da9c01d9cac6252c2。G00-03/04有据签收，G00-01/02和G01尚有剩余项，不宣称G00整阶段完成。无GitHub/云端修改或付费调用。
- G00环境探针实际推进：scripts/probe_office_startup.py在本机分别DispatchEx Excel.Application和ket.Application，比较启动前PID集合与窗口所属PID；两者均是新进程、Workbooks.Count=0，探针只Quit自己创建的空实例，不打开文件。证据outputs/nl_acceptance/office-startup-fd5836925c1c4cc69cff80be5b0931a4/result.json。新增3项防关闭既有/非空实例安全测试，与导出清单测试合计6 passed，Ruff通过；脚本已进入发布显式清单。
- G00-04签收范围严格限于前置环境验证：此前WebEngine独立冻结探针、DPAPI合成往返，加本轮Office/WPS真实启动，以及已集中登记的账号/预算/站点缺口。不是正式客户端EXE、Word/Excel生成保真、仅Office/仅WPS/未安装机器矩阵的签收；这些仍在G11待验。
- 新UTF-8子进程入口完整复核483 passed（189/80/214），证据outputs/nl_acceptance/r-d554a44116094ea4bce1816d2b4763ac。本轮无新增代码变更，主要取得实际线上数据库迁移头证据及重新核对映射；不是仅状态复述。目标未完成，G00/G01剩余门禁继续推进。
- G00线上基线实际推进：本次从Zeabur运行中部署详情验证deployment-6aa9225fd3687c7a2564b4f1，单副本/main/Release0.2.5；服务终端执行alembic current只读查询返回0003_review_jobs (head)，数据库与镜像迁移头一致。未发布、升级、重启、备份或还原。精确镜像摘要和备份恢复演练仍未验证，详情见DEPLOYMENT_RECORD首节。
- 逐项映射复核：原计划的ID无NL前缀，首次错误正则得到0项，未作为覆盖证据；修正按原表格ID提取后81项与账本81项一一一致，无缺失/新增。总目标58个G子项也全部映射；此为覆盖完整性，不代表实现均通过。

- 原子写入诊断/加固：本轮未改业务代码先重跑完整入口，179+80+214=473 passed（r-7d5bb77508374f299696e2fb36263709），证明此前WinError 5间歇出现，不能确认具体占用进程。新增可控复现4 failed/2 passed，确认两个写入点共用固定临时名会在交错写入时冲突，且短暂拒绝访问没有恢复措施。统一atomic_json.py：同目录独占临时文件、关闭/fsync后replace，仅WinError 5/32/33最多4次尝试，总等待0.17秒；持续或其他错误照常抛出、不删目标，仅清理本次临时文件。并不替代业务级并发事务/版本锁。
- 专项19 passed，包括真实Windows CreateFile拒绝删除共享句柄占用、释放后恢复、持续拒绝保留旧文件、其他PermissionError不重试和交错写入。定向Ruff通过。改后完整189+80+214=483 passed，证据outputs/nl_acceptance/r-0cd50b1d635245a280eefe51639789f9。原WinError 5占用来源仍未知，不虚报完全确认根因；后续实机仍需监测。
- 独立编码问题已确认：父Python utf8_mode=1/stdout=utf-8，子进程utf8_mode=0/stdout=gbk。验收入口添加-X utf8；参数断言先1 failed/2 passed后3 passed。此修复未当作文件访问故障原因；上述完整进程在入口改动前已启动，下次完整运行再覆盖新入口。无真实模型调用、无发布变更。

- 本轮验证既有生成规则固定门禁，未重复重写：新增DETAIL自动识别与HISTORY本地生成两项真实execute_task回归；队列创建后技能包指纹变化会在模型调用和输出目录创建前拒绝，原件哈希不变、任务failed。版本门禁及邻近14 passed，Ruff通过。
- 发布阻断新证据：完整入口两次在test_hidden_dependency_sheet_cannot_become_issue_source遇到os.replace WinError 5，分别写project.json和progress.json，178 passed/1 failed；证据r-442d61545b7249feb3010a682794e60f、r-7b1e8dca4a7d499e860172fedd5dd3cc。单用例1 passed、编排文件9 passed、直接审核客户端整套179 passed（outputs/nl_acceptance/skill-gate下）。故障限于JSON原子替换调用，外部占用/环境差异根因尚未证实，未修改业务写入逻辑掩盖错误；下一步对比完整入口子进程环境、路径和实际文件占用。不能沿用上一轮471 passed声称本轮完整通过。

- 最新全回归179+80+212=471 passed，证据outputs/nl_acceptance/r-fd3d8f89baa841559a7116c25e702d88。无付费调用、无远端发布变更；G01未整体签收，不能用版本详情可显示替代升级/回退实测。
- G01本地兼容元信息：local_release现在记录客户端协议、支持的数据schema及所有BUILTINS适配器版本；生成类Skill复用locked_template并计算实际模板/包指纹，异常资源标unavailable_or_changed且不泄露原异常内容。版本面板详情已接入，不只生成离线清单。数据schema明确为客户端支持值而非项目实际迁移值；外部Skill兼容与正式EXE资源核对仍待后续。
- 两项新增测试先KeyError红灯，实现后版本/生成专项11 passed，增强面板断言覆盖模板指纹及数据版本解释，定向Ruff通过。锁定模板未修改。

- 最新完整回归179+80+210=469 passed，证据outputs/nl_acceptance/r-26c0d16c635d4f53a6bb77a78f72b2fb；新界面和测试Ruff通过。G01整体仍未签收；尚无正式EXE发布/云端变更，模型消耗仍0元。
- G01迁移界面接入：平台数据目录按钮打开StorageDialog，当前业务worker存在时拒绝；确认后FunctionWorker后台复制/校验，成功才显示切换，失败只给脱敏原因并保留源及未激活副本。项目资料/成果/外部Skill位于原项目目录，不被此操作移动。模态界面阻止本窗口发起新动作，跨进程use锁仍为实际互斥条件；浏览器/更新器后续接入必须完整持锁。
- TDD：初始4 failed；实现时QDialog.finished同名方法引发信号连接失败，已改名。组合测试后连续窗口发生Python Aborted，单测通过；固定QApplication生命周期和Slot声明均未单独解决，去除后台闭包对窗口的引用并在线程结束时显式断连后重复测试通过。新增5次连续失败/关闭保护和主窗口入口回归，存储专项22 passed。未据此推断整个PySide库根因；运行中迁移尚不能取消，关闭被阻止，开始前可取消。不是原审核任务取消链路的验收。

- 最新隔离全回归179+80+204=463 passed，证据outputs/nl_acceptance/r-b5a00540762745c78bbd1741f1b8003e；既有Starlette弃用警告仍在，无新增测试失败。无GitHub/云端变更、无正式EXE、无付费调用。G00/G01仍为未整体验收状态；本轮为实际代码/测试推进，不是外部阻塞等待。
- G01迁移互斥：StoragePreferences.use提供贯穿消费者生命周期的SQLite共享读锁，migrate在复制前BEGIN EXCLUSIVE并立即报告占用；拒绝WAL索引以免读者不能阻止迁移。当前仅提供锁契约，后续浏览器/更新器必须实际持有，尚不开放迁移UI。16项存储专项通过，包含真实子进程持锁竞争和WAL拒绝；定向Ruff通过。
- 本轮曾拟允许不存在的账号子树按空目录迁移，测试出现失败后复查发现无法区分首次未使用与数据丢失，因此撤回该新增行为，保留拒绝迁移并锁定原设置的负面测试；不把该项计为已修复功能。未改变缺盘拒绝、不回落C盘、不删除旧目录的边界。

- G00发布候选导出边界：export_client_release.py新增collect_paths，排除嵌套运行/缓存/下载/凭据目录，路径resolve发生重定向则拒绝；纳入本轮4个验收脚本和delivery说明。当前296个候选文件，尚未认定内容均可公开。仍需独立密钥/客户数据内容检查及与远端差异审查，不能用扩展名白名单替代内容审计。
- 导出测试先2项缺接口失败；初次临时目录父目录缺失已修复测试环境。路径重定向用例因Windows不允许创建符号链接，改为模拟Path.resolve重定向，不宣称真实链接实测。最终3项导出测试、2项相邻测试均通过，定向Ruff通过。完整179+80+199=458 passed；证据outputs/nl_acceptance/r-fa04b3d36c8c4f75958f84fa32d22f6d。无推送、发布、云端写入或付费调用；G00/G01继续执行，未整体签收。

- G01目录迁移核心：storage_migration.py先枚举当前账号目录并校验路径/文件哈希，复制至独立暂存目录，复核源和目标后才切换设置；不删除旧目录、不复制其他账号。storage_preferences.migrate要求明确确认及消费者关闭。初始5项缺方法红灯后实现；加源变化用例共6项通过，新增文件Ruff通过。尚未开放UI，需TaskManager/浏览器/更新器实际空闲联锁后接入，不能将consumers_closed参数本身当作可信空闲证明。
- 本轮完整179+80+196=455 passed；证据outputs/nl_acceptance/r-c2c8e78d88534927bacf89be11d59132。尚无正式EXE/云端发布，未发生付费调用；G00/G01未整体签收。

- G01数据布局接入：storage_preferences.py仅在设置索引中保存账号/目录路径，业务数据仍非系统盘；PlatformWindow/main接入“平台数据目录”与按需选择，不在登录/启动要求目录。初始4项红灯、UI接口1项红灯后实现，存储/UI专项12 passed。既有项目位置不变，缺盘拒绝而不重建；目录切换需迁移，尚未提供迁移UI。
- 本轮完整179+80+190=449 passed；证据outputs/nl_acceptance/r-e10fcdf4256540808e345dfdce2d8d80；存储新模块和测试Ruff通过。尚未打包正式EXE、推送或部署，模型支出0元。

- 本轮G01-03：新增execution_contracts.py中的TaskIdentity/PlanStep/ToolCall/TaskEvent/Artifact/PermissionGrant/PublicError，严格版本/字段/长度/序号及JSON校验。10项负面用例先缺模块红灯；补成功序列化往返。身份与request_id已接入build_task_spec及execute_task，不只是未使用的定义。
- 复现并修正布尔schema_version被当整数接受、空request_id仍可执行、新任务缺request_id三项失败；专项与执行邻近25 passed，新增契约/任务快照定向Ruff通过。其余事件、权限签发/撤销、工具调度和成果注册仍须后续接入，不标G01-03全部通过。
- 本轮完整回归179+80+185=444 passed；证据outputs/nl_acceptance/r-f4fb5d6e4fe54b9da9bbd06582a3f34a。无付费调用、无云端写入、无GitHub发布。下一步继续数据布局接入与统一事件链路；外部备份/签名/OA目标确认仍等待用户回复，不妨碍本地工作。

- 执行前能力预检已接入RemoteSessionClient的route_skill/create_review_job/analyze_materials；三入口×四兼容模式测试先4红、扩展8红再实现。元信息缺失/未来协议拒绝POST；旧服务端只在OpenAPI明确存在POST时兼容。PROTOCOL_COMPATIBILITY.md记录现有范围及未完成项。
- 路由预检前后接入取消令牌，避免预检期间取消后继续POST；专项及邻近27 passed。首次全回归发现版本提示兼容及资料识别mock遗漏两项失败，已修复后重跑；未伪报首次通过。
- 重跑完整179+80+172=431 passed；证据outputs/nl_acceptance/r-dc6d67800db24fc7885687bc260d3bbd。涉及的新测试/路由定向Ruff完成。仍未发布，真实API支出0元。下一步G01统一版本契约及存储布局接入，不将纯接口门禁视作全阶段通过。

- G01兼容元信息推进：服务端新增GET /api/v1/capabilities，仅声明已挂载接口，REPORT_REVIEW_BUILD_SHA须为Git SHA且默认null；客户端读取、校验未知协议并展示真实声明值。接口专项2红→2绿、读取2红→5绿、面板1红→6绿。
- 缺少业务接口的无结构404/405返回专用兼容性错误，路由UI不再笼统网络提示；不重试调用，不把业务model_not_found归为协议错误。完整166+80+171=417 passed，证据outputs/nl_acceptance/r-4a7ad9db040a419dac08432bb47a4f77；随后面板6项专项通过。
- 本轮新增/主要改动文件定向Ruff通过；扩展检查api.py/remote_auth_service.py仍报已有Depends默认参数、旧异常捕获和导入排序等问题，未宣称整体静态检查通过。接口尚未部署；G01协议/能力矩阵及执行前门禁仍未全部完成。

- 本轮继续G01会话存储基础：新增conversation_state.py，持久化task/question/revision/confirmed/cancelled；9项测试（初始8项缺模块红灯，嵌套字段负面用例再现1项红灯），与迁移/store合计24 passed。尚未连接理解控制器或聊天UI，不能宣称自然语言续接完成。
- 发现并复现PlatformStore在数据库运行中移走后创建空替代库：原测试1 failed/6 passed；改为初始化后所有连接仅mode=rw。完整回归165+78+168=411 passed，Ruff通过；证据outputs/nl_acceptance/r-5f099b58d51043709f47559ec7cd4dda。此改动不移动任何实际项目数据库。

- 本轮收口：技术平台最新158 passed；完整三套最近397 passed，之后只新增4个迁移测试（均通过）。独立浏览器EXE探针passed，非正式客户端发布。下一步继续G01接口/存储集成；G00线上迁移版本、发布白名单与Office实际运行仍需核实。
- GitHub分支保护/规则集均未配置，私有仓库规则集受方案限制；Zeabur数据库备份页未列已有备份且自动备份关闭。已异步询问备份/独立恢复费用、签名保管和OA项目；没有生产变更，真实模型累计支出0元。

- 三份计划已全文读取；使用agent-tdd-fix执行测试先行。
- 正在G00：GitHub元信息已核实；线上构建、分支保护、部署关系仍待核查。
- 初始平台136 passed/2 failed，pytest临时目录在C盘触发业务门禁；已修复测试入口而非放宽门禁，详见BASELINE。
- 三套分进程回归165+78+141=384通过；新增基线工具后平台142通过，四项新工具测试通过。
- 已获001账号累计20元测试上限，实际调用0元；OA指定账号允许上传合成文件，具体测试项目待核实。密码不入账本。
- Zeabur可访问，main/*自动部署关系和Dockerfile覆盖已发现；尚未改任何云端设置。
- G00本地门禁通过后，先推进不依赖云端备份/分支保护的G01存储纯逻辑；并未签收G00整体或允许发布。
- 已安装PySide6-Addons 6.11.1；源码WebEngine探针通过。首个冻结探针启动失败：构建误收集Poppler的icuuc.dll，缺少Qt依赖的20个导出符号。按正式构建的隔离PATH方式重建后合成页面加载/内容验证通过，profile/cache均D盘；证据outputs/nl_acceptance/webengine-frozen-clean-20260916/result.json。这是独立探针，不是正式客户端验收。
- 迁移追加真实表结构合成项目：会话/记忆/附件/任务/事件旧记录和备份逐项一致、原附件哈希不变；9项迁移测试通过。外部Skill与升级链路仍待验收。
- 完整回归发现测试目录叠加账号散列超过Windows路径长度限制；新增路径预算测试先失败，缩短测试运行器目录后165+78+154=397 passed。证据outputs/nl_acceptance/r-90b61ac37417476796b358e93be3d112。未削弱业务非系统盘门禁。
- 本地SQLite版本迁移首轮5项红灯后实现备份与事务回滚；专项/邻近15 passed；补充活动任务、并发打开、备份目录故障后14 passed。尚未完成全量历史数据迁移验收。
- G01新增storage_layout.py，修前6项缺模块失败；实现后全平台148通过。补充跨账号路径重定向用例修前1 failed/6 passed，修后与项目目录回归11 passed；主界面尚未接入，G01不得passed。
- 不覆盖现有未提交改动，不修改锁定模板，不对main试推送。

## G清单

| ID | 状态 | 工作 | 证据/下一步 |
|---|---|---|---|
| G00-01 | doing | 核实实际GitHub仓库、默认/部署分支、保护规则和Zeabur自动部署关系；记录当前提交/镜像/数据库迁移版本。 | 待验证 |
| G00-02 | passed | 保留脏工作区，显式collect_paths与不可覆盖候选哈希清单；无git add .或覆盖用户变更 | source-candidates-20260916-g00.json 303项；导出5项/完整488 passed；内容安全审查和独立发布副本留G08/G10，不属于本项已验收范围 |
| G00-03 | passed | 原81项与58个G子项已逐项映射，已有实现/未知项分开登记，三套隔离入口可复现；不把pending误计为完成。 | baseline-20260916-g00-current.json；6项模板/锁定清单与启动基线一致；映射核对及完整回归见检查点 |
| G00-04 | passed | WebEngine独立冻结探针、DPAPI当前用户合成往返、Excel/WPS独立空实例启动均验证；凭据/预算/站点缺口已集中询问。 | BASELINE追加记录及office-startup-fd5836925c1c4cc69cff80be5b0931a4；仅前置环境，G11业务/实机矩阵未通过 |
| G01-01 | doing | 拆分版本化程序、用户数据、缓存、凭据路径；记住项目/数据根，启动不反复要求选目录；缺盘时明确提示不偷偷回落C盘。 | storage_layout/storage_preferences与main/UI已接入；专项12 passed；浏览器/更新器消费者及目录迁移待接入 |
| G01-02 | doing | 实现旧数据可校验迁移和备份；会话/附件/记忆/外部Skill迁移前后逐项一致；不移动或删除原件。 | local_migrations.py：版本拒绝、只读一致备份、DDL回滚、并发幂等已测；全量历史数据/外部Skill待验 |
| G01-03 | doing | 定义带版本的TaskSpec、PlanStep、ToolCall、Event、Artifact、Permission及脱敏错误契约，统一owner/project/session/task/step/request ID。 | execution_contracts.py；task_spec/execution已接入身份；其余执行/事件/成果消费待接入 |
| G01-04 | doing | 建立客户端版本、服务端构建SHA、API能力、数据schema和Skill/模板版本兼容矩阵；增量兼容优先，不以网络错误代替协议不兼容。 | capabilities API/config + release_info/UI已测；完整矩阵和执行前检查待实施 |
| G02-01 | doing | 从用户意图解析目标、对象、版本、排除项、动作和交付件；咨询/澄清不自动执行业务Skill；删除手动Skill切换依赖。 | AgentController/TaskUnderstanding/客户端已接，模拟及安全边界专项通过；真实语义与留出验收未完成 |
| G02-02 | passed | 解析本轮附件、明确文件名和跨轮指代；不能把项目文件库全选为任务输入；存在多义先澄清。 | AgentController仅把本轮勾选ID送入理解请求；旧文件注入被Unknown file reference拒绝且不建任务；同名歧义不猜最新；控制器/解析器/范围/拖拽22项通过 |
| G02-03 | doing | 统一动态Skill能力目录、结构化选择/计划、输入约束和追问续接；网页任务不靠OA关键词硬路由；支持多个Skill组合。 | 内置/外部规则包目录、组合提案确认及真实本地生成接通，684回归；网页能力、完整追问续接与真实语义未验 |
| G02-04 | doing | 扩展服务端skill_routing及必要规划接口；模型输出必须schema校验，客户端Harness再次校验；不相信模型自报权限。 | understand/plan服务端接口与共享schema、客户端复核已测；尚未部署/真实模型验收 |
| G02-05 | doing | 建立至少100条语义用例和独立留出集：否定、纠正、切任务、指代、无附件、OA/非OA、恶意文档指令。安全边界用例100%通过，其余明确目标至少95%；不靠训练集复述冒充泛化。 | 100基础+20留出已冻结，评分/冻结9专项；真实采集、重复及人工复核未完成，不宣称语义通过 |
| G03-01 | doing | 计划式执行、权限门禁、后置验证、失败诊断和检查点；每步记录可审计的简短执行摘要，不要求或存储模型隐性思维链。 | ExecutionStore/StepResults/顺序Harness/receipt/真实适配器接通，684回归；远端恢复与更完整诊断仍待验 |
| G03-02 | doing | TaskManager已替代全局worker存储，三类线程定向归属；UI切换不停止后台任务、停止针对当前会话、关闭等待全部任务及在途资源。真实Excel双预检并发已测；云端及Office并发/恢复门禁待验收。 | 完整757通过，r-573038b10a194a949d8eea83edeb0dff；仅本地并发验证 |
| G03-03 | passed | 停止按钮立即反馈；网络、模型流、子进程/COM步骤协作取消；不得结束用户其他Office进程；服务端取消与客户端状态对齐。取消不等于已提交远程事务回滚。 | 客户端停止立即进入“正在停止”并禁用重复停止；远端取消请求、轮询中断、迟到结果隔离、生成子进程协作取消、资源锁与服务端queued/running取消均有覆盖；相关专项50项通过。生成链路只终止自身创建并持有句柄的子进程，不枚举或结束用户Office进程。 |
| G03-04 | passed | 模型文本增量直接进对应对话，成果链接也在对话；取消成果侧栏依赖。提供阶段进度，不编造百分比，不把完成文本打字动画称为真实流。 | 服务端每批验证后发布增量issues，客户端轮询在最终响应前转发output事件；TaskEventRelay按不可变owner/project/session/task绑定写入原对话，切换会话不串屏且finished后拒绝迟到输出。审核报告、批注及生成成果链接由对话渲染；UI无成果侧栏。进度仅报告解析、重连、批次完成和校验阶段。远端增量/预检/事件路由/成果交付与取消邻域共50项通过。 |
| G03-05 | passed | 服务端持久任务状态、单任务执行抢占/租约、重复execute幂等；长任务与HTTP请求寿命解耦，重启后无永久running。首版可用数据库持久队列/租约，不强制新增Redis。 | POST execute改为202受理，独立ReviewJobExecutor使用单工作线程和独立数据库会话执行；数据库queued→running原子领取并记录worker租约，重复execute复用同一job；启动时把上次进程遗留running恢复为queued并重投。执行前上下文过期等失败会落失败终态并释放零费用冻结。服务端全量200项及异步/租约/恢复专项通过。首版仍按Zeabur单副本部署。 |
| G03-06 | passed | 实现事件序号/游标和断线续接、终态查询、心跳/超时分类；原始模型流不默认长期存库；任务正文加密临时保留最长24小时。 | 0006迁移新增metadata-only递增事件表、事件游标API、event_sequence及worker lease心跳分类；客户端支持事件游标读取并将202任务轮询到终态，断线只查询原job且不重提付费调用。模型上下文/结果继续加密且最长24小时，事件不保存原始正文。服务端200项、客户端远端邻域28项通过。 |
| G03-07 | doing | 钱包原子预占、模型实际usage归一、重试/切备用渠道账务幂等、取消与失败结算、过期hold处理；模型与路由价格仍不传客户端。 | 用量可信度27关联通过；未知费用核对、预算硬边界、并发与恢复仍待实现验证 |
| G04-01 | passed | 项目树展开多个会话；新建、重命名、归档、未读及运行状态；从指定消息分叉，保存parent/fork与上下文快照。 | 项目树保持多项目同时展开，切换会话隔离草稿；后台运行/未读徽标不切换当前对话；新建、重命名、归档/恢复与指定消息分叉均接入UI和持久层。项目树/会话/消息分叉/徽标/分支上下文专项36项通过。 |
| G04-02 | passed | 独立会话不继承旧附件/授权；分支只继承已完成事实引用，不复制执行中动作和写授权；成果引用固定版本。 | 分支快照仅保存来源消息哈希及锚点前已完成结果引用；草稿、附件选择、运行中动作和权限回执不复制。后代读取重验来源、成果哈希、路径和版本，跨账号、变更锚点及越权提升均拒绝。分支上下文/草稿/文件范围/权限专项39项通过。 |
| G04-03 | doing | 客户端实际HTTP model2、DETAIL生成子进程office1、生成目录排他及等待取消已接；在途HTTP不因caller取消释放。服务端审核执行器固定单任务，标签排他已测。 | 客户端同时两个model租约可进入且第三个等待；服务端两个不同任务由单工作线程串行，24项资源锁/审核任务专项通过。本机 Office+WPS 并存场景分别完成真实 Excel 和强制 WPS 明细表生成，退出码0、来源/模板哈希不变、95 sheet交付门禁和1,322个汇总公式保护通过；结束后无本轮新建进程残留，测试前已有的 WPS 进程保持不动。证据 `D:/ZQ-Acceptance/office-wps-real-acceptance.json`。隔离 PostgreSQL 16.2 从空库迁移到 `0007_skill_releases`，真实并发验证同请求预占幂等、超额预占阻止和重复 capture 单次扣款全部通过，证据 `D:/ZQ-Acceptance/postgresql-wallet-concurrency.json`。独立客户端进程间资源锁仍待验证，暂不签收整项。 |
| G05-01 | doing | 通用面板、地址/标签/导航、主页/书签、下载/冷恢复及用户弹窗已接；隐藏保留网站状态。 | 真实Qt及本机HTTP测试、928完整回归；真实站点和EXE未验收 |
| G05-02 | doing | 账号/environment Profile及存储锁、导航/请求/弹窗/TLS拒绝策略；捕获仅ApplicationWorld窄通道，MainWorld无宿主入口。 | 合成页/真实本机HTTP/进程锁与928回归；真实TLS/复杂站点及EXE仍待验 |
| G05-03 | doing | 捕获→内存加密候选→当前标签明确确认成功并同意→保存/更新已接；暂不/never/恢复、删除及多账号填充可用。 | 真实Qt合成DOM+DPAPI+UI通过；成功依赖用户确认，SPA/多步骤/真实提交导航/OA未验，不标完整通过 |
| G05-04 | doing | DPAPI当前Windows用户、账号/环境/来源隔离、无明文降级；密码仅本地可信捕获/填充链路。 | 篡改/复制/未授权保存、落盘及测试输出检查通过；模型观察全链路/跨Windows账号/更新保留待验 |
| G05-05 | doing | 用户确认填充已接，一次页面ticket和精确来源/表单校验；Agent网站账号授权未实现。 | 真实合成DOM及UI通过，非Agent使用许可；复杂登录/验证码/真实站点未验收 |
| G06-01 | passed | 通用open/navigate/observe/click/fill/select/login/scroll/wait/download/upload工具和可信登录工具；输入输出契约、页面版本与标签租约齐全，禁止任意代码执行工具。 | `browser.execute`使用固定工具目录和严格Pydantic契约；每次动作重验标签租约、页面版本、来源和持久任务状态，下载/上传另有本机完整性回执。无任意脚本/代码执行动作。原生Windows入口浏览器相关393项通过。 |
| G06-02 | passed | 用户自然语言、Skill要求均能调用；普通手动浏览不需任务；Agent不能偷读无关标签；用户接管立即停止后续动作。 | Agent理解结果的browser分支已接`start_browser_task`和专属BrowserTaskHost；手动面板保持独立。跨标签观察受租约隔离，接管使当前租约及迟到回调失效。自然语言→确认→浏览器任务、切会话拒绝及接管专项包含在393项回归。 |
| G06-03 | passed | 网站业务授权绑定具体对象/成果/动作；明确任务可构成该动作授权，有歧义再问；网页提示注入不能扩大权限。 | 总任务授权绑定owner/project/session/task及允许来源/动作；每个写动作再绑定step claim、tab、page version、origin、target和payload摘要，原生确认后发放60秒一次性回执并先消费后派发。网页文本只作为不可信观察，不能创建权限；歧义返回对话追问。并发消费、撤权、换claim、接管、跨账号和提示文本专项通过。 |
| G06-04 | passed | OA先走原流程，用合成成果和获准测试项目验证查找→上传→回执。必要OA源码修改另列必要性、接口契约、测试及授权，不自动重构OA。 | 使用获准账号和测试项目 `实验项目`（project 20）完成登录、定位、上传合成文件及回执核验。首次请求出现服务端已持久化但客户端显示 `Network Error` 的不确定响应；OA 独立提交 `25d9189171596e233b0771d4d7b87ec7e46d4ae2` 增加新文件 ID、类别、阶段、文件名及大小联合回执复核，避免重复上传。OA 前端 9 项测试、类型检查、生产构建通过，Zeabur 服务 `69e07d34345a78e2a2f77776` 部署运行；线上复测显示“上传完成”100%及 `oa-synthetic-upload.txt 当前版本 · 183 B`，未点击提交审核。证据：`D:/ZQ-Acceptance/oa-upload-acceptance.json`。 |
| G06-05 | pending | 非OA站点验证查询和已保存账号登录/下载；页面刷新、跳转、超时、重复提交和多标签身份变更均有测试。 | 待验证 |
| G07-01 | passed | 报告审核、评估明细表、工商沿革及外部Skill接入统一契约；不重写锁定模板；Office/WPS真实生成与格式/链接验证。 | Skill契约、内置模板、安装、组合任务和生成套件59项通过。真实评估明细表生成`run_zdhyse1y`退出码0；锁定`template.xlsx`的10,123个公式位置及链接部件无变化、sheet顺序保持。工商Word字体/段落格式和锁定模板、报告审核只读同步均在上述回归中。 |
| G07-02 | passed | 单/组合审核报告和成果进对话；前台/后台批注询问同事务落盘，后台不弹到其他会话；只授权副本。 | 审核交付/标准Word/批注/后台补问/组合步骤/导出/诊断42项通过，完整平台897项及报告客户端223项通过。成果按所属步骤注册并显示对话链接；拒绝批注不写文件，接受时只生成授权副本，原件哈希门禁保留。 |
| G07-03 | passed | 保留可追溯问题证据、去重、修订状态；执行失败说明阶段/原因/恢复方式，不能只给笼统网络提示。 | `review_issues`按文件、类别、位置和规范化问题生成稳定SHA256指纹，合并精确重复、保留证据摘要及定位哈希，记录new/persistent/resolved轮次状态；无文本证据明确标为unverified。证据/导出/匹配31项、诊断邻域42项及完整897+223回归通过。 |
| G07-04 | passed | 用户/项目/会话记忆分层，来源、确认、过期、删除和优先级；外部Skill风险门禁，用户反馈先成候选规则，经验证再生效，禁止暗改模板/权限。 | 本地schema11新增分层记忆、反馈和改进提案；作用域覆盖、来源/版本/到期/撤回/优先级及UI历史入口齐全。忽略不提案，误判/漏判/偏好仅生成证据绑定候选，命名测试全部通过才可validated，客户端无publish。外部包仍限数据文件和只读/生成能力。服务端`0007_skill_releases`提供草稿→批准→稳定→撤回/回滚及管理员审计，不接收提示词/客户原文。新增及邻近61+31+20+14+7项、完整平台897/服务端205/报告客户端223项通过；线上部署留G09/G10。 |
| G08-01 | passed | 经确认的发布副本有正确.gitignore/.dockerignore和依赖锁；同步白名单含新增模块、CI、部署和必要空白资源；扫描密钥、客户数据及模板残留；不自动恢复源工作区删除文件。 | 独立发布副本 `D:/ZQ-Acceptance/release-checkout`；新增 `.dockerignore` 排除业务目录、凭据、KEY/私钥、DB及缓存；跟踪文件与发布包秘密模式扫描无命中。 |
| G08-02 | passed | CI跑客户端无GUI单测、服务端契约/数据库迁移、静态检查、安全负面测试；Windows job构建客户端，Linux job构建服务端镜像；离线/mock测试不消耗真实API。 | GitHub `05208b17...`：客户端 run `35235669171` 的回归与 Windows build 均 success；服务端 run `35235669071` success；候选 artifact `10503820169` 已生成；Release 资产提升 run `35236865624` success。 |
| G08-03 | passed | 新增签名清单、包哈希、协议/schema范围、平台架构、可信key ID和发布说明；私钥放受控签名环境/GitHub受保护Secret，不进服务端普通变量或仓库；建立轮换/撤销机制。 | `v0.2.7` sequence 2、schema 11、protocol 1、key ID `zq-release-20260917`；CI 包清单 SHA256 `c4e47adb...` 已由客户端内置公钥复验；私钥仅在用户授权的 `D:/1/KEY`，未入仓库/镜像/Zeabur变量。 |
| G08-04 | passed | EXE与资源完整包及独立updater；后台下载、验签、等待空闲、迁移前备份、切换、健康检查和回退。签名更新不等于Windows代码签名，Authenticode有证书再配置，不声称已具备。 | 更新链 98 passed；CI 包内主 EXE 原生健康/登录探针通过；普通包 `1bb4b712...`、托管接管包 `20efa9c3...`。仅应用级 Ed25519 签名，明确无 Authenticode。 |
| G08-05 | passed | 服务端新增客户端发布查询/管理和总控页面：draft/canary/stable/withdrawn、灰度、管理员鉴权、审计；只引用已验证签名包，管理员不能临时绕过签名发布。 | 客户端发布总控栏线上可见；发布服务只接收可信签名清单并支持 draft/canary/stable/withdrawn；服务端205项及权限/签名负测通过，线上能力含 `client_release:1`。 |
| G08-06 | passed | 发布到GitHub Release或经确认HTTPS分发源；包名和版本不可变，旧URL不覆盖不同内容；私有源采用安全下载机制，客户端无仓库PAT。 | 公共 GitHub Release `v0.2.7` 已发布且指向 `05208b17...`；7 项资产均为 `uploaded`。公开清单 `c4e47adb...` 下载后由内置公钥复验，公开普通包摘要 `1bb4b712...` 与 CI 资产一致；客户端无需仓库 PAT。服务端稳定通道登记另由 G10-04 跟踪。 |
| G08-07 | doing | 使用含历史项目的测试数据完成N→N+1→N+2及一次失败恢复；数据、附件、外部Skill、记忆与密码库保留；旧程序无更新器时提供一次性保留数据的过渡安装包。 | 本机隔离副本完成两次升级、失败健康检查、进程中断恢复、数据库指纹和项目清单测试；0.2.7 托管接管包已生成。独立干净Windows实机升级仍缺环境，不计最终通过。 |
| G09-01 | passed | 更新服务端Docker构建清单/requirements/部署文档，共享契约可导入；桌面WebEngine/Office依赖不装入Linux服务镜像。 | 服务端 CI 与 Linux Docker build success；根及部署 Dockerfile 仅安装服务端依赖并显式复制迁移/静态资源，未带入桌面 WebEngine/Office 运行时。 |
| G09-02 | passed | 完成数据库增量迁移：任务/事件/幂等/租约/发布元数据；必要索引、唯一约束和清理策略；备份恢复演练；单执行者迁移，首版保持一个服务副本直到扩容验收。 | Zeabur 日志确认 `0006_review_job_events -> 0007_skill_releases` 成功且单副本启动；迁移/约束测试通过。隔离 PostgreSQL 16.2 执行 `pg_dump -Fc` 后恢复到独立库，17 张表的表名、行数、字段结构及 `0007_skill_releases` head 全部一致；证据 `D:/ZQ-Acceptance/postgresql-backup-restore.json`。未对生产库执行破坏性回退。 |
| G09-03 | passed | 环境变量逐项与代码定义一致，保留现有JWT及供应商加密密钥；所有新增变量提供校验/default说明；生产缺关键值fail-closed，不使用开发回退。 | Zeabur 保留既有秘密变量；公开构建标识单独设置为完整提交 `05208b17...`，线上能力接口精确返回该值；配置校验与缺关键值失败测试通过。 |
| G09-04 | doing | 配置事件流的代理/应用超时与连接恢复；数据库、任务队列、过期hold/临时正文清理、发布下载源健康指标；日志仅脱敏ID和错误分类。 | 事件游标/心跳/租约/重连、24小时正文清理和发布下载完整性已有实现及回归；Zeabur健康与启动日志正常。独立运行监控和报警阈值尚未形成最终运维回执。 |
| G09-05 | doing | 先隔离环境验证新服务与旧客户端/新客户端，确认授权与费用后跑最小真实模型调用；再备份生产并部署指定提交，检查构建SHA、迁移head、健康、登录、总控、模型、任务、取消与账务。 | 指定提交已部署，health、capabilities、迁移head、总控及发布能力已验证；真实模型最小调用、取消与账务回执仍待执行，额度上限为用户授权的20元。 |
| G10-01 | passed | 在已核实的发布仓库使用codex/前缀分支逐阶段提交，CI通过后按保护规则合并；不force-push，不顺手提交无关变动；OA有必要变更则单独提交/发布记录。 | 主仓库在 `codex/platform-sync-20260917` 分支逐阶段提交并以快进方式推送 `main`，发布源提交 `05208b17...` 的 Windows/服务端/Release 资产工作流均成功；后续账本提交 `83212f1...` 的客户端 run `35255331932` 与服务端 run `35255331940` 也均成功。仓库未配置经典分支保护，已作为基线风险记录。OA 必要修复使用独立分支和提交 `25d9189...`，未混入主仓库。 |
| G10-02 | passed | 先部署兼容新旧客户端的服务器，确认就绪后才激活客户端更新通道；若推送即自动部署，发布前控制触发分支/窗口，不能在未就绪main上试错。 | Zeabur 服务先部署 `05208b17...`，迁移 head、health、capabilities、登录、总控及旧稳定版 `0.2.6` 查询均验证通过；截至本项签收时稳定通道仍保持 `0.2.6`，未在服务器就绪前激活新客户端。 |
| G10-03 | passed | 用验收的同一提交重建EXE及压缩包；保留老稳定版，不覆盖运行中的EXE；启动截图、文件版本、资源清单、SHA256、签名与Git标签一致。 | GitHub Windows run `35235669171` 从发布源提交 `05208b17...` 构建 artifact `10503820169`；CI 普通包 SHA256 `1bb4b712...`、托管包 `20efa9c3...`，签名清单 `c4e47adb...`。公开 Release `v0.2.7` 标签固定在同一提交，7 项资产完整；CI 包在隔离目录解压并通过版本、schema、WebEngine、Skill、登录窗口冒烟。旧稳定版未覆盖。 |
| G10-04 | doing | 灰度机器从旧版实际更新到新版本；验证登录、历史、分支、真实流式、取消、浏览器密码和成果；成功后再将该已验收版本设stable。 | 本机隔离副本已完成 N→N+1→N+2、失败健康检查和中断恢复，CI 包启动冒烟通过；总控已登录并成功创建签名校验通过的 `v0.2.7` sequence 2 草稿。账号 `001` 尚无可复用客户端 refresh token，真实模型流式/取消/账务验收未执行；stable 激活等待管理员最后确认。 |
| G10-05 | passed | 生产和客户端回退演练使用隔离副本，不对真实生产随意降库；线上故障先撤回新更新通道并按兼容矩阵处理，不能旧EXE直接打开不兼容新库。 | 更新器专项 98 项覆盖签名/包篡改、迁移前备份、失败健康检查、进程中断恢复、版本切换与回退；两次升级和失败恢复均在 D 盘隔离副本完成，未对真实生产降库。回退与兼容顺序见 `NL_DEPLOYMENT_ROLLBACK.md`。 |
| G11-01 | pending | 全部专项+完整回归、迁移、两次升级、回退、Office/WPS/并存/未安装门禁、中文路径及输入法、干净Windows实机验证。 | 待验证 |
| G11-02 | pending | 原81项与V2每项均有证据；发布阻断项为零。缺真实OA/Office环境等必须记未验收，不以mock通过替代。 | 待验证 |
| G11-03 | pending | 提供中文总结、EXE/压缩包绝对路径、GitHub提交/Release链接、总控地址、部署ID、测试计数、已知限制、恢复方法和回退步骤。 | 待验证 |
| G11-04 | pending | 最终检查无秘密/客户资料公开、无原件越权写入、无隐藏内容外发、无跨账号串用、无重复计费/提交；达到后才标目标完成。 | 待验证 |

## 原81项逐项映射（未以旧完成状态抵扣）

| 原ID | 对应阶段 | 状态 | 原施工内容 |
|---|---|---|---|
| NL00-01 | G00/G08/G11 | pending | 增  /  DOC/NL_BASELINE.md  /  记录 Git 状态、当前源码、EXE、ZIP、服务器构建/协议、模板及 Skill 哈希；未验证处写未知  / 
| NL00-02 | G00/G08/G11 | pending | 增  /  DOC/NL_ACCEPTANCE_LOG.md  /  分阶段记录命令、退出码、用例数、失败、复测、风险和签收，不覆盖失败证据  / 
| NL00-03 | G00/G08/G11 | pending | 改  /  scripts/check_technical_platform.py  /  纳入新增测试目录，支持明确的测试产物目录和报告输出  / 
| NL00-04 | G00/G08/G11 | pending | 改  /  scripts/test_report_review_productization.py  /  纳入平台回归，继续按进程隔离 Qt/旧客户端/服务端测试，保留超时和异常码  / 
| NL00-05 | G00/G08/G11 | pending | 增  /  scripts/check_agent_release_baseline.py  /  只读核对发布文件、规则及模板哈希、测试范围和待验收项；不打印密钥  / 
| NL00-06 | G00/G08/G11 | pending | 复用/补测  /  TTP/test_file_drop.py、test_task_cancellation.py、test_composer_keys.py、test_annotation_followup.py、test_project_catalog.py  /  锁定近期修复和只读/存储范围  / 
| NL00-07 | G00/G08/G11 | pending | 复用  /  DOC/RELEASE_0_2_6.md、AGENT_HARNESS_OPTIMIZATION.md  /  仅作为历史证据，不把旧进度直接改标成新阶段完成  / 
| NL01-01 | G02 | doing | 根包agent_contracts.py共享纯协议，TP/agent_contracts.py转出口；结构/引用负面测试已过，语义与controller接入待完成 |
| NL01-02 | G02 | doing | AgentController无Qt生命周期已接真实UI；问题持久/迟到拒绝/原项目固定；组合计划与完整追问语义仍待验证 |
| NL01-03 | G02 | doing | understanding_policy复用结构/引用校验并按真实适配器格式转追问，已接Controller；完整约束、授权/多目标政策仍待完成 |
| NL01-04 | G02 | doing | UnderstandingWorker使用固定PendingUnderstanding/request_id，可取消且错误不降级；真实UI已接，持久网络恢复待G03 |
| NL01-05 | G02 | doing | 无附件咨询入口已接Controller，单Skill用理解目标范围、旧execute_plan保留授权门禁；组合计划/参考角色与批注接续仍待完成 |
| NL01-06 | G02 | doing | understand_task能力预检/鉴权/取消/二次校验已测；Qt工作线程接入待完成 |
| NL01-07 | G02 | doing | task_understanding.py复用计费代理，JSON Schema与有界上下文；模拟模型测试通过，真实语义验收待完成 |
| NL01-08 | G02 | doing | prompts/task_understanding.txt已创建并列入发布清单；提示词效果待独立留出集与真实API验证 |
| NL01-09 | G02 | doing | 新POST /api/v1/agent/understand与能力声明、鉴权和响应结构测试通过；共享schemas独立放根包；未部署 |
| NL01-10 | G02 | pending | 改  /  SRV/services/skill_routing.py  /  旧 /skill-route 保持兼容适配；不得在旧客户端缺少授权信息时开放新写入能力  / 
| NL01-11 | G02 | pending | 改/增  /  TTP/test_automatic_routing.py；增 test_task_understanding.py；TSRV/test_skill_routing.py；增 test_task_understanding.py  /  模型模拟、JSON 缺失/越界、未知 ID、鉴权、取消和旧协议测试  / 
| NL02-01 | G01/G02/G04 | doing | TP/conversation_state.py + test_conversation_state.py：版本和问题单次绑定、取消失效、跨账号/会话拒绝，待controller/UI接入 |
| NL02-02 | G01/G02/G04 | doing | reference_resolver.py精确文件名/ID/哈希及歧义候选、限定范围和账号校验已测；上传批次、问题/成果指代及理解接口尚待接入 |
| NL02-03 | G01/G02/G04 | doing | file_scope.py角色互斥、ID/哈希冻结；已接TaskSpec/执行入口；自然语言范围与UI联动、参考/排除执行语义待完成 |
| NL02-04 | G01/G02/G04 | pending | 改  /  TP/context.py  /  在理解前构建相关上下文；加入 Agent 的未决询问及受控成果摘要，排除无关旧指令  / 
| NL02-05 | G01/G02/G04 | pending | 改  /  TP/material_analysis.py  /  必要时只读识别资料类型；按需使用安全片段，不把通用意图理解与整文件解析绑死  / 
| NL02-06 | G01/G02/G04 | pending | 改  /  TP/store.py、project_catalog.py  /  新状态按 owner/project/session 隔离；迁移和读取错误不自动创建替代工作区  / 
| NL02-07 | G01/G02/G04 | doing | TP/local_migrations.py内置参数固定的v1 DDL（未另增SQL资源，避免冻结资源漏装）；版本、事务、备份和旧数据保留已测；完整更新器迁移待验 |
| NL02-08 | G01/G02/G04 | pending | 改  /  TP/app.py、task_spec.py  /  上传批次有 ID；同名版本更新可解释；冻结选定文件和理解版本  / 
| NL02-09 | G01/G02/G04 | pending | 复用/补测  /  RA/services/document_extraction_service.py、privacy_filter.py  /  继续使用现有可见性门禁；不得为指代解析单独绕开过滤读取隐藏内容  / 
| NL02-10 | G01/G02/G04 | pending | 增  /  TTP/test_conversation_state.py、test_reference_resolver.py、test_file_scope.py、test_local_migrations.py  /  多轮、跨会话、版本、迁移和歧义测试  / 
| NL02-11 | G01/G02/G04 | pending | 改  /  TTP/test_context.py、test_file_drop.py、test_store.py、test_project_catalog.py  /  防止旧行为回归  / 
| NL03-01 | G02/G03/G07 | doing | skill_contracts.py及4份平台sidecar已进理解链；角色/可选/输出/门禁/环境；通用工具依赖与运行时版本绑定待完成 |
| NL03-02 | G02/G03/G07 | doing | capability_registry已依据真实内置适配器/模板校验生成有限摘要；外部统一发现/检索及完整工具就绪仍待完成 |
| NL03-03 | G02/G03/G07 | doing | tool_contracts.py声明4个现有适配器边界并约束ExecutionPlan；调度资源锁/通用ToolResult及运行时权限服务尚待接入 |
| NL03-04 | G02/G03/G07 | pending | 改  /  TP/skills.py、skill_package.py、skill_installation.py、skill_manager.py  /  支持新契约、旧包兼容和启用检查；安装/启用/可执行状态分开  / 
| NL03-05 | G02/G03/G07 | doing | 四份JSON已实现并接理解请求，明确当前适配器与原Skill能力差异；打包/导出参数通过测试，正式EXE资源验收待G10 |
| NL03-06 | G02/G03/G07 | pending | 改  /  .codex/skills/valuation-report-review-edit/skill.manifest.yaml；valuation-detail-workbook-fill/skill.manifest.yaml；gongshang-change-history-docx/skill.manifest.yaml  /  补齐契约或明确映射到平台 sidecar；兼容原有 CLI 使用，避免重复规则漂移  / 
| NL03-07 | G02/G03/G07 | pending | 改  /  TP/review_rules.txt、TP/task_spec.py、SRV/services/task_understanding.py  /  规则版本、平台只读审核能力和原技能编辑能力明确区分；客户端/服务端协议一致  / 
| NL03-08 | G02/G03/G07 | pending | 增  /  TTP/test_skill_contracts.py、test_capability_registry.py、test_tool_contracts.py  /  输入输出、可选资料、未知工具、冲突能力、版本固定测试  / 
| NL03-09 | G02/G03/G07 | pending | 改  /  TTP/test_skill_package.py、test_skill_installation.py、test_skill_manager_ui.py、test_review_skill_sync.py、test_detail_skill_update.py  /  外部包与模板指纹兼容回归  / 
| NL04-01 | G03/G09 | doing | 单适配器已接TaskSpec；组合PlanProposal编译保留步骤目标/约束/角色，绑定请求与文件范围，DAG/格式/成果类型负测通过；模型提案服务与UI入口、成本类别仍待完成 |
| NL04-02 | G03/G09 | doing | harness顺序DAG调度核心及逐步持久结果已测；真实业务适配器/UI入口、租约、恢复续执行和细粒度状态仍待完成 |
| NL04-03 | G03/G09 | doing | permissions接新UI任务及execute_task；完整快照/输出目录receipt、撤回与失效负测通过；细粒度步骤/问题/浏览器动作及历史v1仅显示策略仍待完成 |
| NL04-04 | G03/G09 | doing | event_store接真实单适配器执行；原子领取/顺序事件/终态checkpoint及会话打开补齐终态缺口已测；远端状态核对、活性证明及通用多步骤恢复仍待完成 |
| NL04-05 | G03/G09 | doing | tool_dispatcher白名单、typed ToolOutcome和真实review/generation单任务已接；artifact_registry校验生成主成果后供只读步骤消费。通用步骤参数/参考角色、annotation/report_export适配器仍待接通 |
| NL04-06 | G03/G09 | doing | 新建TaskSpec v2、v1历史去授权/禁止执行、独立receipt强制门禁及计划/范围必备校验已接通并测；通用多步骤Harness入口仍待完成 |
| NL04-07 | G03/G09 | doing | 按现有Python事务迁移框架在local_migrations.py实现schema 2计划/步骤/事件及schema 3授权表，不并行引入SQL迁移器；备份/回滚/并发升级已测，后续租约/步骤产物等字段仍待完整调度契约 |
| NL04-08 | G03/G09 | pending | 改  /  TP/generation.py、generation_worker.py、annotations.py、excel_annotations.py、report_export.py  /  统一工具结果和原件/模板校验；可取消边界必须真实，不强杀 Office 进程  / 
| NL04-09 | G03/G09 | pending | 改  /  RA/services/remote_review_llm.py、remote_auth_service.py、task_cancellation.py  /  幂等标识、远端状态查询、取消确认、迟到结果处理和重连  / 
| NL04-10 | G03/G09 | pending | 改  /  SRV/services/review_job_service.py、metered_model_service.py、wallet_service.py  /  将计划步骤与原计费/hold对应；使用量及结算以服务端为准，避免重复扣款  / 
| NL04-11 | G03/G09 | pending | 改  /  SRV/api.py、schemas.py、models.py  /  定义状态/事件/取消查询协议；仅保存必要云端执行元数据  / 
| NL04-12 | G03/G09 | pending | 条件增  /  DEP/migrations/versions/<next_revision>_agent_step_state.py  /  若新增云端状态列/表则使用实际 Alembic head 生成修订号，禁止猜编号；无表变更则记录无需迁移  / 
| NL04-13 | G03/G09 | pending | 增  /  TTP/test_planner.py、test_harness.py、test_permissions.py、test_task_recovery.py、test_event_store.py  /  步骤依赖、变更、取消、授权复用、恢复和幂等  / 
| NL04-14 | G03/G09 | pending | 改  /  TTP/test_execution.py、test_task_claim.py、test_task_spec.py、test_task_cancellation.py；TSRV/test_review_jobs.py、test_metered_model_service.py、test_billing_api.py、test_migrations.py  /  旧任务、计费、数据库和取消链路回归  / 
| NL05-01 | G07 | pending | 增  /  TP/followup_controller.py、review_actions.py  /  绑定 task_id/issue_id/version，处理解释、忽略、复核、批注和导出  / 
| NL05-02 | G07 | pending | 增  /  TP/artifact_registry.py、output_validation.py  /  统一成果来源、文件哈希、验证状态、位置数量、问题数量和失败原因  / 
| NL05-03 | G07 | pending | 增  /  TP/ui/conversation_presenter.py、approval_panel.py、task_progress.py、artifact_links.py  /  对话渲染、必要授权、真实阶段/事件进度、文件及目录入口  / 
| NL05-04 | G07 | pending | 改  /  TP/app.py、composer.py  /  app 保留窗口装配，业务逻辑逐步移出；保留 Enter/Alt+Enter、拖拽与滚动行为  / 
| NL05-05 | G07 | pending | 改  /  TP/annotations.py、excel_annotations.py、report_export.py、diagnostics.py  /  统一接入工具/成果协议；逐文件成功和失败单独登记；不得用保存成功替代业务真实性  / 
| NL05-06 | G07 | pending | 增  /  TP/migrations/003_review_actions_artifacts.sql  /  问题操作、成果及每轮后续询问状态持久化  / 
| NL05-07 | G07 | pending | 条件增/改  /  SRV/services/review_conversation.py；SRV/api.py、schemas.py  /  仅在现有模型接口无法支持按问题解释时新增受控对话接口，走相同鉴权/计费/范围门禁  / 
| NL05-08 | G07 | pending | 增  /  TTP/test_followup_controller.py、test_review_actions.py、test_artifact_registry.py、test_output_validation.py、test_task_progress.py  /  自然语言接续、错轮次、防伪成果、事件恢复测试  / 
| NL05-09 | G07 | pending | 改  /  TTP/test_annotation_followup.py、test_export.py、test_composer_keys.py、test_file_drop.py、test_window.py、test_diagnostics.py  /  保真、拒绝/取消、不重复询问、历史入口、快捷键回归  / 
| NL05-10 | G07 | pending | 条件增  /  TSRV/test_review_conversation.py  /  若新增问题对话接口，验证账号、问题范围、幂等和费用  / 
| NL06-01 | G07/G08 | passed | `memory_contracts.py`、`memory_service.py`、`memory_retrieval.py`：来源、用户/项目/会话范围、有效期、状态、版本、优先级和撤销；任务上下文只取当前账号及当前范围的有效值。 |
| NL06-02 | G07/G08 | passed | `feedback_service.py`、`skill_improvement.py`：忽略/误判/漏判/坏建议/偏好分型；只有非忽略反馈且绑定证据才形成候选，关联测试通过后仅变为validated，不自动发布。 |
| NL06-03 | G07/G08 | passed | `context.py`、`store.py`、`skill_installation.py`：撤回即时停止注入，历史任务快照保留ID；账号/项目/会话隔离；外部Skill保持数据包及权限白名单，切换不影响活动任务。 |
| NL06-04 | G07/G08 | passed | 本地schema11增量迁移及`ui/memory_panel.py`：旧项目记忆迁移、来源/范围/状态/版本可见、明确确认后新增、撤回入口；无业务内容默认写系统盘。 |
| NL06-05 | G07/G08 | passed | `skill_release_service.py`：通用Skill草稿、批准、稳定、撤回和旧版回滚；公共响应不含验证证据哈希或客户原文。 |
| NL06-06 | G07/G08 | passed | 服务端models/schemas/api及总控页面已接Skill版本治理；仅管理员可写，客户端仅能读取稳定元数据，无法自授管理权限。 |
| NL06-07 | G07/G08 | passed | 新Alembic head `0007_skill_releases`基于真实`0006_review_job_events`，含版本唯一约束、状态索引及不可静默丢弃的审计表。 |
| NL06-08 | G07/G08 | passed | 新增memory/service/retrieval/improvement及server skill release测试；覆盖冲突、过期、撤回、跨账号、无证据、测试失败、越权、分阶段发布和回滚。 |
| NL06-09 | G07/G08 | passed | context/store/迁移/安装/UI/总控邻域回归及三套全量：平台897、服务端205、报告客户端223全部通过。 |
| NL07-01 | G02/G08/G09/G10/G11 | doing | tests/agent_acceptance/cases/五类JSONL及holdout.jsonl、manifest.json；100+20人工合成用例已冻结，独立复核及真实模型验证待完成 |
| NL07-02 | G02/G08/G09/G10/G11 | doing | tests/agent_acceptance/scoring.py及scripts/evaluate_agent_semantics.py；七维标签、分组/安全/留出门禁及冻结校验已实现，真实回放及副作用授权验收未完成 |
| NL07-03 | G02/G08/G09/G10/G11 | passed | scripts/run_agent_e2e.py：输入消息→结构化理解→明确确认→只读执行→原件哈希复核→不可覆盖证据成果；确定性本地探针不冒充真实模型语义验收；3项专项及控制器/Harness组合22项通过，实跑证据 D:/ZQ-Acceptance/e2e-dff1df8-evidence.json |
| NL07-04 | G02/G08/G09/G10/G11 | passed | release_info/API config/RemoteSessionClient：客户端版本、协议、服务端构建SHA、能力及稳定发布可独立验证；缺能力/未来协议在业务POST前按具体能力阻止。兼容邻域62项通过，线上构建SHA与GitHub提交一致。 |
| NL07-05 | G02/G08/G09/G10/G11 | doing | build/package/export已校验模板、规则、迁移资源和运行时数据排除；新增run_agent_e2e已补入显式源清单并由9项发布清单测试覆盖；最终EXE/ZIP重建及清单哈希复核仍待G10/G11。 |
| NL07-06 | G02/G08/G09/G10/G11 | pending | 改  /  scripts/smoke_technical_platform_exe.py  /  登录、输入法/快捷键、拖拽、对话路由、取消及成果入口的 EXE 冒烟  / 
| NL07-07 | G02/G08/G09/G10/G11 | pending | 改  /  DEP/Dockerfile、requirements.txt、start.py、README.md、ZEABUR.md  /  仅按实际新增依赖和启动迁移需求修改；明确密钥、持久卷、清理任务及兼容升级顺序  / 
| NL07-08 | G02/G08/G09/G10/G11 | pending | 改  /  TTP/test_release_info.py、test_build_dependencies.py；TSRV/test_openapi_contract.py、test_migrations.py  /  新旧协议矩阵、打包资源、迁移及缺能力提示  / 
| NL07-09 | G02/G08/G09/G10/G11 | pending | 增  /  DOC/NL_SEMANTIC_ACCEPTANCE.md、NL_WINDOWS_ACCEPTANCE.md、NL_DEPLOYMENT_ROLLBACK.md、NL_RELEASE_MANIFEST.json  /  用例标签/评分、实机矩阵、发布回退和最终源码/EXE/ZIP/服务端哈希证据  / 
| NL07-10 | G02/G08/G09/G10/G11 | pending | 改  /  DOC/RELEASE_READINESS_CHECKLIST.md、README.md  /  入口、用户操作、能力边界、已验证及待验证状态更新  / 

## 2026-09-17 signed updater integration

- Release branch commit `77139f8` adds the signed update core: manifest verification, trusted-key allowlist, HTTPS host pinning, bounded ZIP extraction, package hash/size checks, SQLite backup/restore, installation journal, process lock, launcher, health-check mode, and independent updater CLI. User project/history data is kept outside the version directory and is backed up before activation.
- The client task manager and Office/resource lock now expose an idle update barrier. New work is rejected while the barrier is held; active work is not force-killed. This is a preparation gate, not an implicit installation consent.
- Local verification on a non-system temporary volume: `tests/platform_update` passed 85/85; combined server and update suites passed 278/278. The update suite covers two sequential versions, failed health recovery, tampered signatures/packages, redirects, archive traversal, process loss, and lock races.
- A Windows GitHub Actions client workflow was added in commit `bdedd0b` to run the client/update suites on a non-system basetemp. The two workflows for this commit were observed as `in_progress` at ledger update time; their final conclusions and any Zeabur rebuild still require confirmation.

## 2026-09-17 client CI collection fix

- GitHub client run `35203892656` for commit `24563dc` failed during test collection because the release checkout omitted the existing support module `scripts/windows_file_owners.py`; this was a packaging/repository completeness defect, not an updater assertion failure.
- Restored the support module in commit `f42beb1` and pushed it to `main`. Targeted local verification (`tests/technical_platform/test_file_owners_probe.py` plus `tests/platform_update`) passed 91/91. The new GitHub client run must complete before this gate is considered passed.
- The next client run exposed a stale acceptance assertion: `test_acceptance_runner.py` still expected three subprocess suites after `platform_update` was added. Updated the expected suite count to four in commit `c2bb0bf`; the focused acceptance-runner verification passed 6/6. GitHub CI and Zeabur must still be rechecked against this newest commit.
- The full client run then reached 987 passing tests and exposed a missing release asset (`assets/report_review/zq_app_icon.png`) in the isolated checkout. Copied the tracked product icon into commit `ec591a3`; the next client run is required to confirm the full suite.
- The subsequent GitHub client run for `4f2aad0` completed with the same Windows-only download-integrity failure at `browser_download_artifacts.py:64`; local full `tests/technical_platform` verification passed 877/877, while the GitHub failure remains an unresolved cross-run/environment discrepancy. Zeabur deployment `Record-client-icon-asset-fix` is running and the online release endpoint still serves stable `v0.2.6`; online capabilities remain build `07e4846...`, so updater-source deployment identity is not yet proven.

## 2026-09-17 Windows CI closure and deployment identity follow-up

- GitHub run `35207236598` showed that Windows `Path.stat()` and handle-based `fstat()` can expose different `ctime` views for one unchanged file. A failing regression was added first; commit `1aded0b` removed `ctime` from the identity stamp while retaining regular-file/link-count, device, inode, size, mtime and streamed SHA-256 checks. The download/confirmation/native-upload neighborhood passed 54/54 locally.
- The next Windows run exposed checkout-dependent CRLF conversion in the byte-frozen 100+20 semantic corpus. Commit `4f1bda2` adds repository attributes that force the frozen corpus and manifest to LF without weakening byte-hash verification. The new checkout-stability test and all semantic-corpus tests passed 5/5 locally; the existing unrecorded-byte-edit rejection remains green.
- Local combined client regression completed successfully: `tests/platform_update`, `tests/technical_platform` and `tests/report_review_app` passed 1183/1183 in 589.48 seconds. The new line-ending test was added after that run and passed in its focused suite.
- GitHub Windows client run `35209923070`, job `105164736275`, completed `success` for commit `4f1bda2`; GitHub server run `35209923133` also completed `success`. This closes the current repository CI blocker but does not by itself prove installed EXE or online deployment identity.
- Online capability metadata still reported stale build `07e4846fcb291ba73077a5fd458db769fd9a3ea8`, while the signed stable release endpoint remained healthy at `v0.2.6`. Zeabur officially exposes `ZEABUR_GIT_COMMIT_SHA` during Git builds, so a new image-only build stamp (`REPORT_REVIEW_IMAGE_BUILD_SHA`) now takes precedence over the optional generic runtime stamp. The Dockerfiles and config were changed test-first; 10 focused tests and the full server suite 194/194 passed. Deployment and online SHA equality remain pending after push.
- Zeabur deployment of commit `cc0c0a7625e03e1daa3840b30f6418345dc8611d` proved that this service mode does not expand the literal runtime value `${ZEABUR_GIT_COMMIT_SHA}`. The strict SHA validator correctly rejected startup and the failed deployment entered crash retry; that failure is retained as evidence rather than hidden. `REPORT_REVIEW_BUILD_SHA` was restored to the exact 40-character commit and the service was redeployed.
- Recovery verification passed: `/api/v1/health` returned `status=ok`; `/api/v1/capabilities` returned build SHA `cc0c0a7625e03e1daa3840b30f6418345dc8611d`, exactly matching the deployed GitHub commit; `/api/v1/client-releases/current` still returned stable signed `v0.2.6`. Zeabur documentation now requires an explicit release SHA for this deployment mode. Automating that configuration update from a protected release workflow remains future hardening; the current deployment identity itself is authoritative.

## 2026-09-17 attachment-scope and stable-release verification

- Commit `dff1df8e2d4ac84d0d43063cfe45c7e7984e3bb4` closes G02-02 with an adversarial controller test: only the explicitly selected current-turn attachment is sent to task understanding, and a model-supplied historical file ID fails closed with `Unknown file reference` before any task is created. The controller/reference/file-scope/file-drop suite passed 22/22 locally.
- Zeabur was redeployed with the exact same 40-character build identity. `/api/v1/health` returned `status=ok`, and `/api/v1/capabilities` returned build SHA `dff1df8e2d4ac84d0d43063cfe45c7e7984e3bb4`, matching GitHub `main` exactly.
- The admin release surface lists `0.2.6 · windows/x86_64 · stable · sequence 1`. The public `/api/v1/client-releases/current` endpoint independently returned the same stable version and manifest SHA-256 `e43f17ed364cbb578c30832fd94f52478d15ec71b6877c1e61fe3afbafc5f0ac`, with the signed GitHub Release download URL. No second transition was submitted because the release was already stable.
- GitHub server run `35212126632` and Windows client run `35212126619` both completed successfully for this commit. This closes the repository CI gate for `dff1df8`.
- NL07-03 now has an executable local acceptance entry point. Three script-contract tests passed, and the AgentController/Harness neighborhood passed 22/22 on a non-system pytest base directory. A real local run produced `D:/ZQ-Acceptance/e2e-dff1df8-evidence.json`, covering message intake, deterministic structured understanding, explicit authorization, read-only execution, source-hash verification and append-only evidence output. The evidence explicitly states that it neither calls a paid model nor proves semantic accuracy or release approval.
- Follow-up commit `e70b21437ad5b6dc372de4c7713317fccf54627d` was deployed after synchronizing the exact build SHA. GitHub server run `35213084169` and Windows client run `35213084195` both completed successfully. Online health remained `ok`, capabilities reported the exact `e70b214...` build, and the stable signed `v0.2.6` release remained available.
- GitHub repository settings were inspected read-only: the repository is public, the default branch is `main`, and no classic branch protection is configured. This is an explicit baseline risk, not an implied protected-release guarantee; no permission/ruleset change was made.
- Protocol/release compatibility verification passed 62/62 tests across release metadata, capability preflight, session, planning and browser-step clients. Unsupported or future capability metadata prevents the relevant business POST and raises a capability-specific error. NL07-04 is signed off; broader G01-04 remains open for the complete data/Skill/template compatibility matrix.

## 2026-09-17 durable review execution and event cursor

- Review execution is no longer coupled to the lifetime of the POST request. The execute endpoint records an idempotent execution request, returns HTTP 202, and a bounded process-local executor opens an independent database session. The database transition from queued to running is atomic and carries a worker lease; the initial Zeabur deployment remains intentionally single-replica.
- Startup recovery converts work left in running by the previous process back to queued, records a recovery event, and resubmits the same job. Provider batch request IDs and the existing round hold remain unchanged, so restart recovery does not create a second paid request.
- Migration `0006_review_job_events` adds a metadata-only ordered event stream, cursor index, execution-request timestamp and worker lease fields. The authenticated event endpoint returns only status metadata after `after_sequence`; it does not persist prompt text, document text, model output text, API keys, prices or worker identity.
- Job snapshots now classify an active versus stale worker heartbeat without exposing lease or worker identifiers. The client accepts HTTP 202, polls the original task to a terminal state, distinguishes a stale worker from a network-unknown task, and never resubmits an ambiguous paid call.
- A pre-claim failure fallback was verified test-first: an expired encrypted context now moves the requested job to a safe failed state, emits terminal metadata, releases the zero-cost round hold, and makes no provider call. This prevents permanent queued jobs and stale balance reservations.
- Verification used the isolated release checkout with `PYTHONPATH` pinned to that checkout. The complete server suite passed 200/200; the focused OpenAPI/capability/review contract passed 23/23; remote client, release-export and migration coverage passed 37/37 from a non-system pytest directory. The admin UI visibly lists `0.2.6 · windows/x86_64 · stable · sequence 1`; no duplicate stable transition was submitted.
- Commits `199872d` and `708ff9c74fa3e28710a962eeeb457b4df6e26b6e` were pushed to `main`. GitHub server run `35217603887` and Windows client run `35217603893` both completed successfully. Zeabur deployment `6aabd40d56a7d809491d5bb4` ran migration `0005_client_releases -> 0006_review_job_events`; health returned `ok`, capability metadata matched the exact `708ff9c...` commit and advertised `review_events: 1`, while the stable signed `0.2.6` release remained unchanged.
