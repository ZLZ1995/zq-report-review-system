# 工作流契约

工作流契约是用户确认业务规则与技能实现之间的交接文件。推荐保存为 UTF-8 JSON。

## 最小结构

```json
{
  "schema_version": "1.0",
  "proposed_skill_name": "monthly-sales-report",
  "purpose": "根据月度销售表和固定模板生成管理层月报",
  "audience": "销售负责人",
  "triggers": ["生成本月销售月报"],
  "inputs": [
    {
      "name": "月度销售明细",
      "formats": ["xlsx"],
      "required": true,
      "authority": "财务确认后的月结表",
      "example": "2026年8月销售明细.xlsx"
    }
  ],
  "steps": [
    {
      "id": "S1",
      "action": "读取销售明细并按区域汇总",
      "decision": "缺少区域时请求用户补充映射，不自行归类"
    }
  ],
  "exceptions": [
    {
      "condition": "关键输入缺失或无法识别",
      "action": "说明缺失内容和影响，向用户询问处理方案"
    }
  ],
  "outputs": [
    {
      "name": "销售月报",
      "format": "docx",
      "naming_rule": "销售月报_YYYYMM.docx",
      "preserve_template": true
    }
  ],
  "acceptance_criteria": [
    "区域合计与输入表一致",
    "最终 DOCX 已逐页渲染检查且无截断"
  ],
  "office_routes": [
    {
      "skill": "spreadsheets",
      "responsibility": "读取、汇总并核对 Excel"
    },
    {
      "skill": "documents",
      "responsibility": "按模板生成并渲染检查 Word 报告"
    }
  ],
  "proof_run": {
    "sample_inputs": ["2026年8月销售明细.xlsx", "销售月报模板.docx"],
    "expected_output": "销售月报_202608.docx",
    "synthetic_sample_allowed": false
  },
  "open_questions": [],
  "confirmation": {
    "workflow_confirmed": true,
    "ready_to_build": true,
    "confirmed_by": "用户",
    "confirmed_at": "2026-09-17"
  }
}
```

## 字段要求

- `proposed_skill_name`：小写英文、数字和连字符；不得用宽泛名称代替真实目标。
- `purpose`：一句话说明输入经过什么处理，形成什么结果。
- `triggers`：用户日后会自然说出的触发语句。
- `inputs`：列出格式、是否必需、权威来源和样例；图片也要列为输入。
- `steps`：按业务顺序描述，分支或判断写在对应步骤中。
- `exceptions`：至少覆盖缺少关键输入、格式无法识别、规则冲突或无匹配结果时如何向用户询问。
- `outputs`：写明格式和命名；如基于模板，声明是否必须保留版式。
- `acceptance_criteria`：必须可观察或可计算，不能只写“质量好”。
- `office_routes`：只列实际需要的办公技能及其职责。
- `proof_run`：必须有代表性样例；合成样例需取得用户同意。
- `open_questions`：只要非空，就不能进入创建。
- `confirmation`：两个布尔值都为 `true` 后才能创建或更新 skill。

## 确认摘要

向用户展示时使用业务语言，推荐五段：

1. 何时启动；
2. 需要提供什么；
3. 系统会怎样处理；
4. 例外时会怎样询问；
5. 交付什么以及怎样验收。

