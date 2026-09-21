from __future__ import annotations

BALANCE_SHEET_LABEL_NORMALIZATION = {
    "应收票据及应收账款": "应收账款",
    "应付票据及应付账款": "应付账款",
    "预收款项": "预收账款",
    "实收资本（或股本）": "实收资本",
}

NONCURRENT_ASSET_SHEET_MAPPING = {
    "长期股权投资": {"sheet": "股权投资", "bs_line": "长期股权投资", "policy": "placeholder_only"},
    "投资性房地产": {"sheet": "4-5-1投资性房地产", "bs_line": "投资性房地产", "policy": "placeholder_only"},
    "固定资产": {"sheet": "固定资产汇总", "bs_line": "固定资产", "policy": "placeholder_only"},
    "在建工程": {"sheet": "在建工程汇总", "bs_line": "在建工程", "policy": "placeholder_only"},
    "工程物资": {"sheet": "工程物资", "bs_line": "工程物资", "policy": "placeholder_only"},
    "固定资产清理": {"sheet": "固定资产清理", "bs_line": "固定资产清理", "policy": "placeholder_only"},
    "生产性生物资产": {"sheet": "生产性生物资产", "bs_line": "生产性生物资产", "policy": "placeholder_only"},
    "油气资产": {"sheet": "油气资产", "bs_line": "油气资产", "policy": "placeholder_only"},
    "使用权资产": {"sheet": "使用权资产", "bs_line": "使用权资产", "policy": "placeholder_only"},
    "无形资产": {"sheet": "无形资产汇总", "bs_line": "无形资产", "policy": "placeholder_only"},
    "开发支出": {"sheet": "开发支出", "bs_line": "开发支出", "policy": "placeholder_only"},
    "商誉": {"sheet": "商誉", "bs_line": "商誉", "policy": "placeholder_only"},
    "长期待摊费用": {"sheet": "长期待摊费用", "bs_line": "长期待摊费用", "policy": "placeholder_only"},
    "递延所得税资产": {"sheet": "递延所得税资产", "bs_line": "递延所得税资产", "policy": "placeholder_only"},
    "其他非流动资产": {"sheet": "其他非流动资产", "bs_line": "其他非流动资产", "policy": "placeholder_only"},
}

CURRENT_LIABILITY_SHEET_MAPPING = {
    "短期借款": {"sheet": "短期借款", "bs_line": "短期借款", "policy": "placeholder_only"},
    "交易性金融负债": {"sheet": "交易性金融负债", "bs_line": "交易性金融负债", "policy": "placeholder_only"},
    "应付票据": {"sheet": "应付票据", "bs_line": "应付票据", "policy": "placeholder_only"},
    "应付账款": {"sheet": "应付账款", "bs_line": "应付账款", "policy": "detail_fillable"},
    "预收账款": {"sheet": "预收账款", "bs_line": "预收账款", "policy": "detail_fillable"},
    "应付职工薪酬": {"sheet": "职工薪酬", "bs_line": "应付职工薪酬", "policy": "detail_fillable"},
    "应交税费": {"sheet": "应交税费", "bs_line": "应交税费", "policy": "detail_fillable"},
    "应付利息": {"sheet": "应付利息", "bs_line": "应付利息", "policy": "placeholder_only"},
    "应付股利": {"sheet": "应付股利（利润）", "bs_line": "应付股利", "policy": "placeholder_only"},
    "其他应付款": {"sheet": "其他应付款", "bs_line": "其他应付款", "policy": "detail_fillable"},
    "一年内到期的非流动负债": {"sheet": "一年到期非流动负债", "bs_line": "一年内到期的非流动负债", "policy": "placeholder_only"},
    "其他流动负债": {"sheet": "其他流动负债", "bs_line": "其他流动负债", "policy": "placeholder_only"},
}

NONCURRENT_LIABILITY_SHEET_MAPPING = {
    "长期借款": {"sheet": "长期借款", "bs_line": "长期借款", "policy": "placeholder_only"},
    "应付债券": {"sheet": "应付债券", "bs_line": "应付债券", "policy": "placeholder_only"},
    "长期应付款": {"sheet": "长期应付款", "bs_line": "长期应付款", "policy": "placeholder_only"},
    "专项应付款": {"sheet": "专项应付款", "bs_line": "专项应付款", "policy": "placeholder_only"},
    "预计负债": {"sheet": "预计负债", "bs_line": "预计负债", "policy": "placeholder_only"},
    "租赁负债": {"sheet": "租赁负债", "bs_line": "租赁负债", "policy": "placeholder_only"},
    "递延所得税负债": {"sheet": "递延所得税负债", "bs_line": "递延所得税负债", "policy": "placeholder_only"},
    "其他非流动负债": {"sheet": "其他非流动负债", "bs_line": "其他非流动负债", "policy": "placeholder_only"},
}

OWNER_EQUITY_SHEET_MAPPING = {
    "实收资本": {"sheet": "00000000", "bs_line": "实收资本", "policy": "direct_balance_sync"},
    "资本公积": {"sheet": "00000000", "bs_line": "资本公积", "policy": "direct_balance_sync"},
    "减：库存股": {"sheet": "00000000", "bs_line": "减：库存股", "policy": "direct_balance_sync"},
    "其他综合收益": {"sheet": "00000000", "bs_line": "其他综合收益", "policy": "direct_balance_sync"},
    "专项储备": {"sheet": "00000000", "bs_line": "专项储备", "policy": "direct_balance_sync"},
    "盈余公积": {"sheet": "00000000", "bs_line": "盈余公积", "policy": "direct_balance_sync"},
    "未分配利润": {"sheet": "00000000", "bs_line": "未分配利润", "policy": "direct_balance_sync"},
}
