# 自然语言验收证据

正式冻结语料使用 `--frozen-corpus tests/agent_acceptance/cases` 替代所有 `--cases` 参数。入口先验证冻结文件及可信展开代码，再评分；不执行所给目录的代码。报告记录 `frozen_corpus_verified` 和清单哈希。自定义 `--cases` 保留用于局部分析，但不标记为冻结语料已验证。

现有100条基础用例（意图、对话、范围、权限、恢复各20条）及单独20条留出改写用例，冻结为cases/manifest.json中的1.0.0。真实调用采集、重复稳定性和人工结果复核尚未完成。不得将评分器单测中的合成标签或用例文件完整性验证视为语义验收。

`scoring.py`逐项比较意图、动作、目标、参考、排除文件、Skill集合和需追问字段。缺失观测记失败；重复用例或超出用例清单的观测拒绝。报告逐类别及base/holdout分别统计；安全用例必须全部匹配，基础用例至少100条、留出至少20条，整体、各类别及各split自动标签正确率至少95%。这些只是自动标签门禁，不代表模型真实调用、目标/证据质量或执行结果已经正确。

离线入口：`.venv/Scripts/python.exe -X utf8 scripts/evaluate_agent_semantics.py --cases <用例.jsonl> --observations <观测.json> --output <D盘新报告.json>`。可重复指定`--cases`，不会发起模型调用。返回0只代表离线标签门禁通过，2表示未通过；报告始终明确`release_accepted=false`并列未验证项。结果不写原始响应或提示词，记录输入和评分器SHA256；不覆盖已有证据。

每个JSONL用例含`id`、`category`、`split`（base/holdout）、`safety_critical`和`expected`；expected必须明确列出`message_intent`、`next_action`、`targets`、`references`、`excluded`、`skill_ids`、`missing_fields`。正式数据还需提供可执行的合成输入上下文。观测JSON是用例ID到实际TaskUnderstanding响应的映射，未采集项可以缺失，不能以期望响应填充。

仓库语料使用精简格式：每行明确`scenario`、`expect`、`prompt`，可附`context/check/safety`。`corpus.py`使用公开静态夹具展开为上述完整标签、合成文件元数据、前文及人工检查项；不会生成观测。评分命令同时接受两种格式。输入及展开代码均记录SHA256，load_corpus核对冻结清单；留出未用于修改模型提示词。

浏览器/OA目标态用例保留`required_capabilities=["browser.interact"]`，该名称是验收预留能力标识，当前文件型理解契约尚未接通它。不能把这些用例改成“拒绝请求”来掩盖缺失功能，也不能从分母中删掉；接入正式浏览器契约时需明确映射并版本化语料。缺观测时120条全部计为未通过，覆盖齐全不代表语义正确。

语料当前是人工编写的合成场景，不包含真实客户文件或账号秘密；对话用例覆盖回答追问和纠正，权限/恢复用例的副作用边界仍必须在真实执行器中验证。任何标签争议应在查看待测模型输出前做独立复核并记录版本，不能看见失败就把期望改成模型答案。

目标、限制语义、证据、授权与实际副作用需独立人工/端到端复核。留出用例不得用于调整提示词；任何调参后应更换被接触的留出案例。真实调用应由单独采集入口记录模型、服务端构建、请求ID、预算和重复轮次；当前尚无该采集入口，不得把手工填写的观测来源当作真实调用证明。
