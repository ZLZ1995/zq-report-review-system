def test_plan_confirmation_describes_transfer_scope_and_selected_files():
    from asset_based_agent.technical_platform.plan_confirmation import confirmation_text
    snapshot = {'mode': 'browser_task', 'user_request': '上传本次审核报告', 'model': 'm',
                'browser_scope': {'environment': 'test', 'origins': ['https://example.com'],
                                  'actions': ['observe', 'upload', 'download']},
                'upload_artifacts': [{'artifact': {'name': '本次报告.docx', 'size': 3,
                                                   'sha256': 'a' * 64}}]}
    text = confirmation_text(snapshot, 'D:/synthetic')
    assert '下载' in text and '上传' in text and '本次报告.docx' in text
    assert '不授权上传本地文件' not in text
    assert '再次确认' in text and '原始资料' in text
