import os
import subprocess
import sys


def test_browser_proposal_respects_shared_model_limit_and_wait_cancel():
    code = r'''
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication
from asset_based_agent.report_review_app.services.resource_locks import CLIENT_RESOURCES
from asset_based_agent.technical_platform.browser_execution_loop import BrowserProposalWorker
app=QCoreApplication([])
called=Event()
class Client:
    def propose_browser_step(self, payload, *, cancel):
        called.set()
        return {'ok':True}
request=SimpleNamespace(model_dump=lambda:{})
with ExitStack() as stack:
    stack.enter_context(CLIENT_RESOURCES.lease(('model',)))
    stack.enter_context(CLIENT_RESOURCES.lease(('model',)))
    cancel=Event()
    worker=BrowserProposalWorker(Client(),request,cancel,None)
    worker.start()
    try:
        assert not called.wait(.25), 'Browser bypassed occupied model resource slots'
    finally:
        cancel.set()
        assert worker.wait(2000)
    assert not called.is_set()
assert not CLIENT_RESOURCES.busy()
worker=BrowserProposalWorker(Client(),request,Event(),None)
worker.start(); assert worker.wait(2000)
assert called.is_set() and worker.result=={'ok':True}
assert not CLIENT_RESOURCES.busy()
class Failure:
    def propose_browser_step(self, payload, *, cancel): raise RuntimeError('secret')
worker=BrowserProposalWorker(Failure(),request,Event(),None)
worker.start(); assert worker.wait(2000)
assert worker.error and worker.result is None and not CLIENT_RESOURCES.busy()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_browser_loop_dispatch_cancel_and_unknown_do_not_replay(tmp_path):
    code = r'''
import json, sys, time
from PySide6.QtCore import QCoreApplication
from test_browser_observer import bound, respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
def wait(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end:
        app.processEvents(); time.sleep(.005)
    assert predicate()
for scenario in ('success', 'cancel', 'unknown', 'takeover'):
    observer, leases, lease, page, _=bound(can_click=lambda *_:True)
    class Client:
        def __init__(self): self.calls=[]
        def propose_browser_step(self, payload, *, cancel):
            self.calls.append(payload)
            return {'request_id':payload['request_id'], 'action':'click',
                    'target':'1', 'summary':'Open project'}
    client=Client(); finished=[]
    loop=BrowserExecutionLoop(client, observer, None, leases, lease,
        task_id='t', model_id='m', goal='Open project',
        scope=BrowserIntent(origins=['https://example.com'], actions=['observe','click']),
        authorized=lambda:True)
    loop.finished.connect(lambda status, detail: finished.append(status))
    loop.start()
    respond(page, controls=[{'id':'1','kind':'button','text':'Open','disabled':False}])
    wait(lambda:len(page.calls)==2)
    assert client.calls[0]['observation']['untrusted'] is True
    if scenario=='cancel': loop.stop()
    elif scenario=='takeover': leases.takeover(page)
    page.calls[-1][2](json.dumps({'status':'unknown' if scenario=='unknown' else 'dispatched'}))
    if scenario=='success':
        wait(lambda:len(page.calls)==3)
        assert not finished
        loop.stop()
    wait(lambda: bool(finished))
    assert finished==['cancelled' if scenario in ('success','cancel','takeover') else 'unknown']
    assert len(client.calls)==1
    assert not loop.isRunning()
print('browser execution loop: ok')
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=35, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_browser_loop_waits_for_cancelled_worker_and_never_auto_accepts_finish():
    code = r'''
import time
from threading import Event
from PySide6.QtCore import QCoreApplication
from test_browser_observer import bound, respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
def wait(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end:
        app.processEvents(); time.sleep(.005)
    assert predicate()
for scenario in ('late', 'finish', 'revoked'):
    observer, leases, lease, page, _=bound(can_click=lambda *_:True)
    entered, release=Event(), Event()
    permitted=[True]
    class Client:
        def propose_browser_step(self, payload, *, cancel):
            entered.set()
            assert release.wait(5)
            return {'request_id':payload['request_id'], 'action':'finish',
                    'summary':'Proposed result', 'evidence':'Visible'}
    loop=BrowserExecutionLoop(Client(), observer, None, leases, lease,
        task_id='t', model_id='m', goal='Read page',
        scope=BrowserIntent(origins=['https://example.com'], actions=['observe']),
        authorized=lambda:permitted[0])
    finished=[]; loop.finished.connect(lambda status, _:finished.append(status))
    loop.start(); respond(page)
    wait(entered.is_set)
    if scenario=='late': loop.stop()
    if scenario=='revoked':
        permitted[0]=False
        loop._tick()
    if scenario!='finish':
        assert loop.isRunning() and not finished
    release.set()
    if scenario=='finish':
        wait(lambda:len(page.calls)==2)
        assert not finished
        respond(page)
    wait(lambda:bool(finished))
    assert finished==['needs_verification' if scenario=='finish' else 'cancelled']
    assert len(page.calls)==(2 if scenario=='finish' else 1) and not loop.isRunning()
print('late worker and result verification: ok')
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=35, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_wait_reobserves_without_blocking_and_stops_on_cancel_or_navigation():
    code = r'''
import time
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from test_browser_observer import bound, respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
for scenario in ('normal','cancel','navigation'):
    observer, leases, lease, page, _=bound()
    class Client:
        def propose_browser_step(self,payload,*,cancel):
            return {'request_id':payload['request_id'],'action':'wait','value':'200','summary':'Wait briefly'}
    loop=BrowserExecutionLoop(Client(),observer,None,leases,lease,task_id='t',model_id='m',goal='Read',
        scope=BrowserIntent(origins=['https://example.com'],actions=['observe','wait']),authorized=lambda:True)
    finished=[]; progress=[]
    loop.finished.connect(lambda status,_:finished.append(status)); loop.progress.connect(progress.append)
    loop.start(); respond(page)
    deadline=time.monotonic()+5
    while not any('等待页面' in p for p in progress) and time.monotonic()<deadline: QTest.qWait(5)
    assert any('等待页面' in p for p in progress)
    if scenario=='cancel': loop.stop()
    if scenario=='navigation': page.urlChanged.emit()
    QTest.qWait(400)
    if scenario=='normal':
        assert len(page.calls)==2 and not finished
        loop.stop()
    else:
        assert len(page.calls)==1
        assert finished==['cancelled' if scenario=='cancel' else 'unknown']
    observer.close(); leases.close()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH']=os.pathsep.join(['src','tests/technical_platform',env.get('PYTHONPATH','')])
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],env=env,capture_output=True,
                          text=True,encoding='utf-8',timeout=20,check=False)
    assert result.returncode==0,result.stdout+result.stderr


def test_completion_requires_fresh_same_page_evidence_before_business_verification():
    code = r'''
import time
from threading import Event
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from test_browser_observer import bound, respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
def wait(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end: QTest.qWait(5)
    assert predicate()
for scenario in ('fresh','missing','navigation','cancel','late_navigation','timeout','revoked'):
    observer, leases, lease, page, allowed=bound()
    entered, release=Event(),Event()
    class Client:
        def propose_browser_step(self,payload,*,cancel):
            entered.set(); assert release.wait(5)
            return {'request_id':payload['request_id'],'action':'finish','summary':'Result proposal','evidence':'Visible'}
    loop=BrowserExecutionLoop(Client(),observer,None,leases,lease,task_id='t',model_id='m',goal='Read',
        scope=BrowserIntent(origins=['https://example.com'],actions=['observe']),authorized=lambda:True)
    finished=[]; loop.finished.connect(lambda status,detail:finished.append((status,detail)))
    loop.start(); respond(page); wait(entered.is_set)
    if scenario=='navigation': page.urlChanged.emit()
    release.set()
    wait(lambda:len(page.calls)>1 or bool(finished))
    if scenario=='navigation':
        assert finished[0][0]=='unknown' and len(page.calls)==1
        continue
    assert not finished, 'Old observation was incorrectly treated as current evidence'
    if scenario=='cancel': loop.stop()
    if scenario=='late_navigation': page.urlChanged.emit()
    if scenario=='revoked': allowed[0]=False
    if scenario=='timeout':
        loop._deadline=time.monotonic()-1
        loop._tick()
    respond(page,text='Missing now' if scenario=='missing' else 'Visible')
    wait(lambda:bool(finished))
    expected='needs_verification' if scenario=='fresh' else 'cancelled' if scenario=='cancel' else 'unknown'
    assert finished[0][0]==expected
    if scenario=='fresh':
        assert finished[0][1]['evidence']=='Visible'
        assert loop.completion_evidence['origin']=='https://example.com'
        assert len(loop.completion_evidence['evidence_sha256'])==64
    else: assert loop.completion_evidence is None
    observer.close(); leases.close()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH']=os.pathsep.join(['src','tests/technical_platform',env.get('PYTHONPATH','')])
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],env=env,capture_output=True,
                          text=True,encoding='utf-8',timeout=30,check=False)
    assert result.returncode==0,result.stdout+result.stderr
