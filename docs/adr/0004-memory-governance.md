# ADR 0004：记忆治理

- 状态：已接受（G04 实施）
- 日期：2026-09-18

## 背景

当前记忆（`memory_service.py` / `memory_retrieval.py` / `memory_contracts.py`）已有：user/project/session 三作用域、kind（preference/fact/instruction）、source（explicit_user/verified_artifact）、确认后写入、撤销、过期、优先级、版本和召回预算。缺口：无 proposed→confirmed 候选生命周期（现在必须 confirmed 才能写）；无 feedback/reference/skill-learning 分型；无后台候选抽取；无冲突检测与合并；无敏感信息扫描门禁。

## 决定

1. 三个存储平面：协作记忆（user/feedback/project/reference）、运行记忆（摘要/未完成任务/澄清链/回执，任务结束归档）、Skill 学习（误判/漏判/验收标签，与正式版本隔离）。
2. 记录状态机：proposed → confirmed → revoked / superseded；带来源消息/任务、版本、有效期、敏感级别、可信度、验证策略。
3. 候选抽取在主回复结束且无活动工具后异步进行，只处理新增消息增量；用户纠正/明确偏好可建议记住，项目事实必须用户确认。
4. 写入前去重、冲突、敏感扫描；召回最多 5 条并带陈旧提示；当前文件证据优先于记忆。
5. 提供本轮忽略、查看来源、撤销、删除项目记忆。

## 替代方案

- 自动把模型推断写入长期记忆：拒绝，本项目涉及财务与客户资料。
- 单一文本记忆池：拒绝，无法表达生命周期和来源。

## 后果

- 新增 `memory_candidates.py`、`memory_selector.py`、`memory_consolidation.py`（G04）。
- `memory_records` 表需要增量迁移（新状态/字段）；旧记录迁移为 confirmed。
- 敏感红线：不记录 API Key、密码、Cookie、客户正文、证件号、银行账号、未脱敏金额。

## 验收

- G04：敏感样本写入率 0；未经确认的项目事实不影响执行；撤销后不再召回；冲突记忆不覆盖当前证据。
