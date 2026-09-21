from __future__ import annotations

from asset_based_agent.report_review_app.branding import (
    APPLICATION_NAME,
    CONFIG_TOOL_NAME,
    application_icon_path,
)


def test_zq_product_branding_and_icon_asset_are_available() -> None:
    assert APPLICATION_NAME == "ZQ评估报告审核系统"
    assert CONFIG_TOOL_NAME == "ZQ评估报告审核系统配置工具"
    assert application_icon_path().is_file()
