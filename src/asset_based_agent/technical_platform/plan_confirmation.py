"""Plain-text scope confirmation; model output never becomes HTML or consent."""
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
)


def confirmation_text(snapshot, root):
    if snapshot.get('mode') == 'browser_task':
        from .browser_task_spec import BrowserTaskScope, browser_execution_goal
        scope = BrowserTaskScope.model_validate(snapshot['browser_scope'])
        labels = {'observe':'读取网页', 'navigate':'浏览网页', 'click':'点击控件',
                  'fill':'填写普通字段', 'select':'选择选项', 'login':'使用已授权的保存账号',
                  'scroll':'逐屏滚动', 'wait':'短暂等待并重新观察',
                  'download':'下载文件（另行确认）', 'upload':'上传所选成果副本（另行确认）'}
        uploads = snapshot.get('upload_artifacts', [])
        upload_scope = ('所选成果：' + '、'.join(item['artifact']['name'] for item in uploads)
                        + '。仅提供所选成果元数据；上传前再次确认网站、业务对象和文件版本，不上传原始资料。'
                        if uploads and 'upload' in scope.actions else
                        '不授权上传本地文件；网站写入和账号使用仍受独立授权约束。')
        return '\n'.join([
            '请确认本轮浏览器任务范围。', '', '你的要求：', snapshot['user_request'], '',
            '完整执行目标（含本轮相关追问与限制）：', browser_execution_goal(snapshot), '',
            '允许的网站：', *scope.origins, '',
            '允许的动作：' + '、'.join(labels[action] for action in scope.actions),
            '环境：' + scope.environment, '模型：' + snapshot['model'],
            f'本地任务记录位置：{root}', '',
            '使用本轮专属标签页，不读取其他标签或历史附件。',
            '任务所需的有限网页观察会发送给模型；网站密码不发送给模型。',
            upload_scope,
            '网页指令不能扩大本轮范围；你可以停止任务或主动接管标签页。',
        ])
    plan = snapshot['execution_plan']
    names = {f['id']: f['name'] for f in snapshot['files']}
    names.update({s['output_ref']: f"步骤成果：{s['goal']}" for s in plan['steps']})
    lines = ['请确认本轮计划。只读取列出的资料，不修改原始文件。',
             f'新成果及临时数据存入：{root}',
             '包含联网模型调用。' if snapshot['permissions']['call_model'] else '执行步骤不调用模型。']
    for index, step in enumerate(plan['steps'], 1):
        lines.extend(['', f"{index}. {step['goal']}", f"使用能力：{step['skill_id']}"])
        binding = snapshot.get('step_configs', {}).get(step['step_id'], {}).get('external_skill')
        if binding:
            lines.append(f"外部规则包：{binding['id']} {binding['version']}；SHA256：{binding['sha256']}")
        for role, title in [('target_inputs', '目标'), ('reference_inputs', '仅作参考')]:
            lines.extend(f'{title}：{names[ref]}' for ref in step[role])
        lines.extend('限制：' + value for value in step['constraints'])
    lines.extend(['', '确认仅授权本轮范围与步骤；新增写入或外部上传仍需另行确认。'])
    return '\n'.join(lines)


class PlanConfirmationDialog(QDialog):
    def __init__(self, snapshot, root, parent=None):
        super().__init__(parent)
        self.setWindowTitle('确认本轮执行计划')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.details = QPlainTextEdit(confirmation_text(snapshot, root))
        self.details.setReadOnly(True)
        self.details.setAccessibleName('本轮任务范围与权限')
        layout.addWidget(self.details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button.setText('确认并执行')
        self.cancel_button.setText('取消')
        if snapshot.get('mode') == 'browser_task':
            self.consent = QCheckBox('我已核对本轮网站、动作与模型使用范围')
            layout.addWidget(self.consent)
            self.confirm_button.setEnabled(False)
            self.confirm_button.setAutoDefault(False)
            self.cancel_button.setDefault(True)
            self.cancel_button.setFocus()
            self.consent.toggled.connect(self.confirm_button.setEnabled)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.resize(760, 560)
