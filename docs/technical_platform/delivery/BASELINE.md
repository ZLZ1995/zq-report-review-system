# G00 基线

2026-09-16。仅记已核实事实，不含凭据。

- 工程源HEAD：cbc7d94293e9d95aa6677ac324939c53d4d955a2；大量脏文件，无remote。不得视为发布仓库HEAD。
- GitHub连接器已确认目标ZLZ1995/zq-report-review-system为private，main，连接具admin/push/pull权限。
- 远端main：d63628c68fbb895103fca1ef7d344145341660ad，提交说明Release 0.2.5。本地源码0.2.6；未据此认定线上版本。
- 初始平台136 passed/2 failed：测试tmp_path落在C盘触发正常业务安全门禁。修复测试入口，不改业务校验。
- 测试入口新用例修前2 failed/1 passed；修复后3 passed。首次全量发现pytest basetemp父目录未创建，新增断言复现后修复；失败证据未掩盖。
- 修正后分进程全量：审核客户端165 passed、服务端78 passed、技术平台141 passed；合计384。服务端有一项Starlette/httpx弃用警告，暂非失败。
- PySide6-Essentials为6.11.1；起始缺PySide6-Addons/WebEngine，安装同版进行中。win32crypt与win32com可导入。
- Excel/Word/ket/kwps的COM注册项存在，只是环境发现，不等于Office/WPS生成或视觉验收。
- 当前Zeabur浏览器页ERR_NAME_NOT_RESOLVED，部署绑定/迁移head/备份待核实；不修改网络安全配置绕过。
- 已获本轮真实API累计20元上限，账号001；实际调用消耗0元。需记录每次请求及前后余额、冻结额，不以未知结果重复调用。
- OA指定账号已获准上传合成文件；目标测试项目尚需在站内核实；不改真实业务记录。不在账本保存密码。

基线工具：scripts/check_agent_release_baseline.py。仅哈希内置模板/技能定义，不遍历客户inputs；原件不作测试素材。

## 追加验证

- 更新只读清单outputs/nl_acceptance/baseline-20260916-g00-current.json；与baseline-20260916-start.json逐项比较builtin_templates及template.lock.json，共6项SHA256完全一致。原81项、58个G子项均已映射，无遗漏；G00-03仅签收映射/基线，不将其误认为81项实现完成。
- Office/WPS真实COM启动：outputs/nl_acceptance/office-startup-fd5836925c1c4cc69cff80be5b0931a4/result.json；Excel.Application与ket.Application均独立新PID、空工作簿，成功退出本探针创建的空实例。未打开/修改原件或模板。安全测试确认已有PID或非空实例不Quit。此证据替代“仅注册存在”的环境级未知项，但不证明完整业务生成和渲染。
- 冻结浏览器首测失败已定位ICU误收集：Qt6Core需要20个icuuc导出而Poppler副本没有。scripts/build_platform_webengine_probe.py沿用正式构建的干净PATH后，独立EXE合成页面验证passed；证据outputs/nl_acceptance/webengine-frozen-clean-20260916/result.json。不是正式客户端发布。
- 本轮全量397 passed（165/78/154），证据outputs/nl_acceptance/r-90b61ac37417476796b358e93be3d112；随后补充迁移边界/数据保留专项9 passed。全量测试中曾暴露Windows路径长度错误，已以短测试产物路径修正并补路径预算回归。

- 基线清单测试修前1 failed（缺模块），实现后与入口测试合计4 passed；技术平台完整复测142 passed；本轮新增/修改Python文件Ruff通过。
- 基线哈希证据：outputs/nl_acceptance/baseline-20260916-start.json。
- 三套隔离回归JUnit：outputs/nl_acceptance/regression-d1994545f7644c37a26dcc8e75221178/。
- DPAPI当前Windows用户合成字节加解密往返通过；不涉及实际密码保存。
- Windows请求health=200，重新打开Zeabur恢复可访问；此前DNS错误不是持续服务故障。部署详情见DEPLOYMENT_RECORD追加段。
- PySide6-Addons 6.11.1安装成功；WebEngine源码合成页面探针passed，证据outputs/nl_acceptance/webengine-source-20260916/result.json。仅验证渲染与目录，不替代真实登录/自动化安全验收。
- 新存储模块前六项通过后平台148通过；另补跨账号路径重定向负面用例并修正，专项+原项目目录11通过。G01实现仍未接入UI，不标阶段完成。
