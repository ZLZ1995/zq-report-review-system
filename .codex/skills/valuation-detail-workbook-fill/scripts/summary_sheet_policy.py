"""Shared summary-sheet identity for registries, writers and validation."""

SUMMARY_SHEET_BASE_NAMES = frozenset({
    '汇总', '分类汇总', '资产评估结果分类汇总', '流动汇总', '流动资产汇总',
    '存货汇总', '非流动资产汇总', '可供出售金融资产汇总',
    '交易性金融资产汇总', '固定资产汇总', '在建工程汇总', '无形资产汇总',
    '流动负债汇总', '非流动负债汇总',
})
SUMMARY_SHEET_NAMES = frozenset(
    name + suffix for name in SUMMARY_SHEET_BASE_NAMES for suffix in ('', '表')
)


def is_linked_summary_sheet(name: str) -> bool:
    return name.strip() in SUMMARY_SHEET_NAMES
