import json
from threading import Event

import pytest
from test_browser_download_integrity import delivered


@pytest.mark.parametrize('change', ['none', 'decline', 'cancel', 'revoke', 'replace', 'manifest'])
def test_download_confirmation_rechecks_delivery_and_authority(tmp_path, change):
    from asset_based_agent.technical_platform.browser_download_completion import (
        confirm_download_delivery,
    )
    from asset_based_agent.technical_platform.browser_download_integrity import (
        verify_download_delivery,
    )
    store, run, path, _, service = delivered(tmp_path)
    cancel = Event()
    manifest = verify_download_delivery(store, run, cancel)
    detail = {'summary': 'Downloaded requested file', 'evidence': 'Download completed'}
    def confirm(snapshot, shown, active):
        assert active()
        assert shown['files'] == manifest['files']
        assert str(path) not in json.dumps(shown)
        if change == 'cancel': cancel.set()
        if change == 'revoke': service.revoke(run)
        if change == 'replace': path.write_bytes(b'changed after confirmation')
        if change == 'manifest': manifest['files'][0]['sha256'] = '0' * 64
        return change != 'decline'
    result = confirm_download_delivery(store, run, cancel, manifest, detail,
                                       confirm=confirm, is_current=lambda: True)
    if change == 'none':
        assert result['method'] == 'user_confirmed_download'
        assert result['task_id'] == run
    else:
        assert result is None


@pytest.mark.parametrize('change', ['task', 'goal', 'file', 'origin', 'stale_context'])
def test_download_confirmation_rejects_mismatched_manifest_before_prompt(tmp_path, change):
    from asset_based_agent.technical_platform.browser_download_completion import (
        confirm_download_delivery,
    )
    from asset_based_agent.technical_platform.browser_download_integrity import (
        verify_download_delivery,
    )
    store, run, _, _, _ = delivered(tmp_path)
    cancel = Event()
    manifest = verify_download_delivery(store, run, cancel)
    if change == 'task': manifest['task_id'] = 'another-task'
    if change == 'goal': manifest['goal_sha256'] = '0' * 64
    if change == 'file': manifest['files'][0]['id'] = 'another-file'
    if change == 'origin': manifest['files'][0]['origin'] = 'https://other.example'
    prompts = []
    result = confirm_download_delivery(
        store, run, cancel, manifest, {'summary': 'file', 'evidence': 'download'},
        confirm=lambda *args: prompts.append(args) or True,
        is_current=lambda: change != 'stale_context')
    assert result is None
    assert not prompts
