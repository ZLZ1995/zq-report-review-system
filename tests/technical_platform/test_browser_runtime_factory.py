import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('scenario', ['normal', 'cancel_during_confirmation', 'revoked',
                                     'unconfirmed', 'wrong_environment'])
def test_native_runtime_uses_claimed_task_and_releases_real_tab(tmp_path, scenario):
    code = r'''
import json, sys, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from test_browser_task_spec import make_browser_run
from asset_based_agent.technical_platform.browser_profile import BrowserSession
from asset_based_agent.technical_platform.browser_task_leases import BrowserTaskLeases
from asset_based_agent.technical_platform.browser_task_host import BrowserTaskHost
from asset_based_agent.technical_platform.browser_runtime_factory import create_browser_runtime
from asset_based_agent.technical_platform.browser_download_controller import BrowserDownloads
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.task_manager import TaskBinding, TaskManager
root=Path(sys.argv[1]); scenario=sys.argv[2]; app=QApplication([])
store,run,project=make_browser_run(root)
(root/'program').mkdir(); (root/'data').mkdir()
prefs=StoragePreferences(root/'index.sqlite',root/'program'); prefs.select('alice',root/'data')
manager=TaskManager(); calls=[]; runtimes=[]
class Client:
    def propose_browser_step(self,payload,*,cancel):
        calls.append(payload)
        return {'request_id':payload['request_id'],'action':'ask','summary':'Which page?'}
with BrowserSession(prefs,'alice',environment='production' if scenario=='wrong_environment' else 'test') as session:
    downloads=BrowserDownloads(session,lambda _:None)
    page=session.new_page()
    leases=BrowserTaskLeases(session,manager); leases.register(page)
    def factory(host):
        def confirm_navigation(*_):
            if scenario=='cancel_during_confirmation':
                host.cancel.set()
                return True
            if scenario=='revoked':
                with store.connect() as db:
                    db.execute('UPDATE execution_authorizations SET revoked=1 WHERE run=?',(run,))
                return True
            return False
        loop=create_browser_runtime(host,Client(),leases,page,confirmed=scenario!='unconfirmed',
            confirm_action=lambda *_:False,confirm_navigation=confirm_navigation,
            select_account=lambda *_:None,downloads=downloads,confirm_upload=lambda *_:False)
        assert loop.uploads is not None and loop.uploads.candidates()==[]
        assert loop.login is not None
        assert loop.downloads.controller is downloads
        assert loop.login.vault.owner=='alice' and loop.login.vault.environment=='test'
        assert loop.navigation.allowed('https://example.com/one')
        assert not loop.navigation.allowed('https://other.test/one')
        assert not loop.navigation.allowed('http://example.com/one')
        results=[]
        loop.navigation.navigate('https://example.com/one',results.append)
        assert results==['rejected'], results
        runtimes.append(loop)
        return loop
    worker=BrowserTaskHost(store,run,runtime_factory=factory)
    worker.binding=TaskBinding('alice',project,store.run(run)['session'],run)
    manager.register(worker.binding,worker)
    worker.finished.connect(lambda:manager.finish(worker.binding,worker))
    worker.start()
    end=time.monotonic()+10
    while worker.isRunning() and time.monotonic()<end: QTest.qWait(10)
    assert not worker.isRunning() and not manager.active()
    result=json.loads(store.run(run)['result'])
    if scenario=='normal':
        assert len(calls)==1 and calls[0]['observation'] is None
        assert result['status']=='needs_input' and result['summary']=='Which page?'
    else:
        assert calls==[] and result['verified'] is False
    if runtimes:
        assert runtimes[0].downloads.closed
        assert runtimes[0].login.closed
        assert runtimes[0].uploads.closed
        assert not leases.valid(runtimes[0].lease)
        assert not runtimes[0].navigation.allowed('https://example.com/one')
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM browser_action_authorizations').fetchone()[0]==0
    downloads.close(); leases.close()
print('native browser runtime: ok')
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path), scenario],
                            env=env, capture_output=True, text=True, encoding='utf-8',
                            timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
