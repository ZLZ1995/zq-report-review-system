# 工商历史沿革模块交接契约

本契约用于让其他 skill 或 agent 消费工商历史沿革模块输出，尤其是正式评估报告修订场景。

## 输出文件

生成流程必须产出以下文件：

- `history_events.json`：结构化事件计划。
- `history_fragment.docx`：可整体插入正式报告的连续历史沿革片段。
- `history_validation.json`：模块级验收结果。

## history_events.json

顶层字段：

- `company_name`：企业名称。
- `events`：保留事件数组，按披露顺序排列。
- `ending_text`：历史沿革结尾说明。

事件字段：

- `date`：`YYYY-MM-DD`。
- `description`：正文事件描述。
- `omitted`：是否省略。
- `omit_reason`：省略原因，可为空。
- `tables`：事件下表格数组。

表格字段：

- `type`：`equity_7col` 或 `normal_3col`。
- `title`：表格标题或项目名称。
- `rows`：表格数据行。
- `append_to_equity`：短事项是否追加至同日股权主表。

## 股权表 schema

`type = equity_7col` 时必须为 7 列：

1. 项目
2. 变更前-股东名称
3. 变更前-出资金额（万元）
4. 变更前-持股比例
5. 变更后-股东名称
6. 变更后-出资金额（万元）
7. 变更后-持股比例

每行字段：

- `project`
- `before_name`
- `before_amount`
- `before_ratio`
- `after_name`
- `after_amount`
- `after_ratio`

硬性要求：

- 表格必须包含两层表头。
- 表格必须包含 `合计` 行。
- 变更前、变更后金额合计必须分别校验。
- 有金额基础时，变更前、变更后持股比例合计必须为 `100.0000%`。
- 同日存在股权实际变更时，股权表是主表；短事项可追加到底部，不得由消费方另起临时股权表。

Additional equity validation requirements:

- Detail rows must sum to the total row on both before/after amount columns.
- Detail rows must sum to the total row on both before/after ratio columns.
- Shareholder rows with a name must include both amount and ratio.
- Shareholder names must be unique on each side of an equity table.
- When `fact_sheet.confirmed_facts` contains equity holder amounts for a date, the corresponding equity table side must exactly match that fact-sheet holder/amount map.

## history_validation.json

必须包含：

- `ok`：总体验收是否通过。
- `checks`：验收项数组。
- `outputs`：输出文件路径。

最低验收项：

- `template_fonts_preserved`：每个非空文字运行的中西文字体与锁定模板一致；缺字体属性视为失败。
- `text_size`：正文12磅、表格9磅；`w:sz` 与 `w:szCs` 均存在。
- `first_line_indent`：正文2字符、表格0，无冲突悬挂缩进。
- `events_order_correct`
- `fragment_docx_exists`
- `equity_table_has_7_columns`
- `equity_table_has_two_level_header`
- `equity_table_has_total_row`
- `equity_before_amount_total_ok`
- `equity_after_amount_total_ok`
- `equity_before_ratio_total_100`
- `equity_after_ratio_total_100`
- `equity_before_amount_sum_matches_total`
- `equity_after_amount_sum_matches_total`
- `equity_before_ratio_sum_matches_total`
- `equity_after_ratio_sum_matches_total`
- `equity_before_shareholder_amount_ratio_complete`
- `equity_after_shareholder_amount_ratio_complete`
- `equity_before_shareholder_names_unique`
- `equity_after_shareholder_names_unique`
- `equity_before_matches_confirmed_fact_sheet`
- `equity_after_matches_confirmed_fact_sheet`
- `normal_table_has_3_columns`

## 消费方规则

消费方只能读取 `history_fragment.docx` 和 `history_validation.json`。

消费方不得：

- 重新解析工商 Excel。
- 自行生成股权表。
- 临时拼接 7 列股权表。
- 绕过 `history_validation.json` 将片段插入正式报告。

若 `history_validation.json.ok != true`，消费方必须停止正式报告写入。
