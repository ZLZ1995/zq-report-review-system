import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('generated', [False, True])
def test_download_continuation_excludes_path_and_cancellation_never_continues(tmp_path, generated):
    code = r'''
import time,sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from test_browser_observer import bound, respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
path=Path(sys.argv[1])/'file.txt'; path.write_bytes(b'data')
def wait(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end: QTest.qWait(5)
    assert predicate()
for cancel in (False,True):
    observer,leases,lease,page,_=bound()
    calls=[]
    class Downloads:
        callback=None
        closed=False
        def begin(self, observation,target,callback): self.callback=callback
        def close(self): self.closed=True
        def commit_verified(self,fingerprint):
            assert len(fingerprint['sha256'])==64 and fingerprint['size']==4
            return {**fingerprint,'task_id':'t','origin':'https://example.com','id':'local-receipt'}
    class Client:
        def propose_browser_step(self,payload,*,cancel):
            calls.append(payload)
            return {'request_id':payload['request_id'],'action':'download' if len(calls)==1 else 'ask',
                    'target':'1' if len(calls)==1 else '', 'summary':'Choose next step'}
    downloads=Downloads()
    downloads.supports_generated=sys.argv[2]=='True'
    loop=BrowserExecutionLoop(Client(),observer,None,leases,lease,task_id='t',model_id='m',goal='Download',
        scope=BrowserIntent(origins=['https://example.com'],actions=['observe','download']),
        authorized=lambda:True,downloads=downloads)
    results=[]; loop.finished.connect(lambda status,_:results.append(status))
    loop.start(); respond(page,controls=[{'id':'1','kind':'button' if downloads.supports_generated else 'link','text':'Report','disabled':False}])
    wait(lambda:downloads.callback is not None)
    assert bool(calls[0].get('generated_downloads')) is downloads.supports_generated
    if cancel: loop.stop()
    downloads.callback('downloaded',{'task_id':'t','name':'file.txt','size':4,
        'origin':'https://example.com','path':str(path)})
    if cancel:
        assert results==['cancelled'] and len(calls)==1 and not loop.download_results
    else:
        wait(lambda:len(page.calls)==2); respond(page)
        wait(lambda:bool(results))
        assert results==['needs_input'] and len(calls)==2
        assert calls[1]['completed_downloads']==[{'name':'file.txt','size':4,'origin':'https://example.com'}]
        assert str(path) not in str(calls)
        assert loop.download_results[0]['id']=='local-receipt'
    assert downloads.closed
    observer.close(); leases.close()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path), str(generated)], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)
    assert result.returncode==0, result.stdout+result.stderr


def test_cancelling_hash_waits_for_worker_without_committing_or_blocking_ui():
    code = r'''
import time
from threading import Event
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication,QThread
from PySide6.QtTest import QTest
from test_browser_observer import bound
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform import browser_download_worker as module
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([]); entered=Event(); release=Event(); commits=[]
def blocked(path,size,cancel):
    assert QThread.currentThread()!=app.thread()
    entered.set(); assert release.wait(5)
    return {'path':str(path),'size':size}
module.fingerprint_download=blocked
observer,leases,lease,page,_=bound()
downloads=SimpleNamespace(close=lambda:None,commit_verified=lambda item:commits.append(item))
loop=BrowserExecutionLoop(None,observer,None,leases,lease,task_id='t',model_id='m',goal='Download',
    scope=BrowserIntent(origins=['https://example.com'],actions=['observe','download']),
    authorized=lambda:True,downloads=downloads)
loop._running=True; finished=[]; loop.finished.connect(lambda status,_:finished.append(status))
loop._download_done('downloaded',{'task_id':'t','path':'D:/synthetic.txt','size':4})
assert entered.wait(2)
loop.stop(); app.processEvents()
assert loop.isRunning() and finished==[]
release.set()
end=time.monotonic()+5
while loop.isRunning() and time.monotonic()<end: QTest.qWait(5)
assert finished==['cancelled'] and not commits and not loop.download_results
observer.close(); leases.close()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=15, check=False)
    assert result.returncode==0,result.stdout+result.stderr
