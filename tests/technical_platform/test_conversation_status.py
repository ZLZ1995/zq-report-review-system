"""S16：会话/轮次状态控制器（测试先行）。

契约（施工文件 4.2）：
- 会话状态携带 session_id；异步回调携带 operation_id；
- 轮次阶段原位更新，终态（完成/失败/取消）替换临时阶段；
- 跨会话隔离：A 的状态不影响 B 的读取；
- 全局通知按 kind 存取，与轮次状态互不干扰。
"""
from asset_based_agent.technical_platform.conversation_status import (
    ConversationStatusController,
)


def test_turn_phase_set_read_and_clear():
    controller = ConversationStatusController()
    controller.set_turn_phase('s1', 'op1', '正在理解本轮要求…')
    phase = controller.turn_phase('s1', 'op1')
    assert phase is not None
    assert phase.phase == 'running'
    assert phase.text == '正在理解本轮要求…'
    controller.clear_turn_phase('s1', 'op1')
    assert controller.turn_phase('s1', 'op1') is None


def test_complete_and_fail_replace_phase_with_terminal_state():
    controller = ConversationStatusController()
    controller.set_turn_phase('s1', 'op1', '正在生成…')
    controller.complete_turn('s1', 'op1', '已生成 3 个文件。')
    done = controller.turn_phase('s1', 'op1')
    assert done.phase == 'completed'
    assert done.text == '已生成 3 个文件。'
    controller.set_turn_phase('s1', 'op2', '正在生成…')
    controller.fail_turn('s1', 'op2', 'model.timeout', '模型超时')
    failed = controller.turn_phase('s1', 'op2')
    assert failed.phase == 'failed'
    assert failed.payload.get('error_code') == 'model.timeout'


def test_status_isolated_across_sessions_and_operations():
    controller = ConversationStatusController()
    controller.set_turn_phase('s1', 'op1', 'A 会话进行中')
    controller.set_turn_phase('s2', 'op9', 'B 会话进行中')
    assert controller.turn_phase('s1', 'op1').text == 'A 会话进行中'
    assert controller.turn_phase('s2', 'op9').text == 'B 会话进行中'
    assert controller.turn_phase('s2', 'op1') is None  # operation 维度隔离
    controller.clear_turn_phase('s1', 'op1')
    assert controller.turn_phase('s1', 'op1') is None
    assert controller.turn_phase('s2', 'op9') is not None  # 不影响 B


def test_latest_phase_of_session_and_global_notices():
    controller = ConversationStatusController()
    controller.set_turn_phase('s1', 'op1', '第一步')
    controller.set_turn_phase('s1', 'op2', '第二步')
    assert controller.turn_phase('s1').text == '第二步'  # 不传 op → 该会话最新
    controller.set_global_notice('connection', '服务已连接')
    controller.set_global_notice('update', '正在下载更新')
    assert controller.global_notice('connection') == '服务已连接'
    assert controller.global_notice('update') == '正在下载更新'
    controller.set_global_notice('connection', None)  # 清除
    assert controller.global_notice('connection') is None
    assert controller.global_notice('update') == '正在下载更新'
