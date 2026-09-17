import os
import subprocess
import sys


def test_upload_loop_routes_metadata_and_waits_for_cancelled_preparation():
    code = r'''
import time
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from test_browser_observer import bound,respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
for scenario in ('dispatch','cancel'):
 observer,leases,lease,page,_=bound()
 class Uploads:
  callback=None
  running=False
  def candidates(self): return [{'id':'a','name':'report.docx','size':3,'sha256':'a'*64}]
  def request(self,observation,proposal,callback):
   assert proposal.artifact_id=='a'; self.callback=callback; self.running=True
  def isRunning(self): return self.running
  def close(self): pass  # Background preparation has not finished yet.
 uploads=Uploads(); seen=[]
 class Client:
  def propose_browser_step(self,payload,*,cancel):
   seen.append(payload)
   return {'request_id':payload['request_id'],'action':'upload','target':'1',
    'artifact_id':'a','object_label':'Project 001','summary':'Upload the report'}
 loop=BrowserExecutionLoop(Client(),observer,None,leases,lease,task_id='t',model_id='m',
   goal='Upload',scope=BrowserIntent(origins=['https://example.com'],actions=['observe','upload']),
   authorized=lambda:True,uploads=uploads)
 finished=[]; loop.finished.connect(lambda status,_:finished.append(status))
 loop.start();respond(page,controls=[{'id':'1','kind':'file','text':'File','disabled':False}])
 end=time.monotonic()+5
 while uploads.callback is None and time.monotonic()<end: QTest.qWait(10)
 assert uploads.callback is not None
 assert seen[0]['upload_artifacts']==uploads.candidates()
 if scenario=='cancel':
  loop.stop(); assert loop.isRunning() and not finished
 uploads.running=False;uploads.callback('cancelled' if scenario=='cancel' else 'dispatched')
 QTest.qWait(50)
 if scenario=='dispatch':
  assert len(page.calls)==2 and not finished
  loop.stop()
 assert finished==['cancelled'] and not loop.isRunning()
 observer.close();leases.close()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
