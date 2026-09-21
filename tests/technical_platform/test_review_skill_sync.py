from pathlib import Path

from asset_based_agent.technical_platform.skills import REVIEW


def test_runtime_review_policy_contains_updated_readonly_boundaries():
    rules = (Path(__file__).resolve().parents[2] /
             'src/asset_based_agent/technical_platform/review_rules.txt').read_text(encoding='utf-8')
    for requirement in ('已确认暂空', '内部模板要求', '本轮无法验证',
                        '观察环境', '不机械截断', '旧意见的保留、降级、撤回及新增'):
        assert requirement in rules
    assert '不修改原始文件' in rules
    assert '隐藏及veryHidden' in rules
    assert '只返回服务端要求的结构化JSON' in rules
    assert REVIEW.version == '0.2.0'
