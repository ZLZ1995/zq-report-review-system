import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('choice', ['accept', 'decline', 'model_changed', 'session_changed', 'upload_accept', 'upload_decline'])
def test_message_routes_to_confirmed_browser_task_without_files(tmp_path, choice):
    code = r'''
import json, sys, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from test_browser_understanding import result_data
from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
root=Path(sys.argv[1]); choice=sys.argv[2]
(root/'program').mkdir(); (root/'data').mkdir()
prefs=StoragePreferences(root/'index.sqlite',root/'program'); prefs.select('alice',root/'data')
store=PlatformStore(root/'project.sqlite','alice')
project=store.create_project('Browser'); session=store.create_session(project)
qt=QApplication([]); calls=[]; confirmations=[]
upload_candidate={'artifact':{'id':'upload-0','name':'synthetic.docx','size':3,'sha256':'a'*64},
 'source':{'run_id':'b'*32,'kind':'generation','index':0,'sha256':'a'*64}}
if choice.startswith('upload_'):
    import asset_based_agent.technical_platform.browser_window as browser_window
    def select_upload(*args):
        calls.append('select_upload')
        return [upload_candidate] if choice=='upload_accept' else []
    browser_window.select_upload_artifacts=select_upload
class Client:
    access_token='synthetic'
    def understand_task(self,payload,*,cancel):
        assert any(s['id']=='browser.task' for s in payload['skills'])
        calls.append('understand')
        result={**result_data(),'evidence_message_ids':[payload['message_id']]}
        if choice.startswith('upload_'): result['browser']['actions'].append('upload')
        return result
    def propose_browser_step(self,payload,*,cancel):
        calls.append('browser')
        if choice=='upload_accept': assert payload['upload_artifacts']==[upload_candidate['artifact']]
        goal=json.loads(payload['goal'])
        assert goal['messages'][-1]['text']=='打开https://example.com并查看公告'
        assert goal['goal']==result_data()['goal']
        assert goal['deliverables']==result_data()['deliverables']
        return {'request_id':payload['request_id'],'action':'ask','summary':'Which announcement?'}
window=PlatformWindow(store,client=Client(),models=[{'model_id':'m','display_name':'Synthetic'}],storage_preferences=prefs)
window.reload_projects(project)
def confirm(snapshot):
    confirmations.append(snapshot)
    assert snapshot['mode']=='browser_task' and snapshot['files']==[]
    if choice=='model_changed':
        window.model_combo.addItem('Other','other'); window.model_combo.setCurrentIndex(1)
    if choice=='session_changed':
        window.reload_sessions(store.create_session(project))
    return choice!='decline'
window.confirm_compound_plan=confirm
window.composer.setPlainText('打开https://example.com并查看公告'); window.submit()
deadline=time.monotonic()+15
while window.task_manager.active() and time.monotonic()<deadline: QTest.qWait(10)
assert not window.task_manager.active()
assert len(confirmations)==(0 if choice=='upload_decline' else 1), window.transcript.toPlainText()
if choice in ('accept','upload_accept'):
    # 两阶段路由（§4.2）：阶段1轻量理解 + 阶段2带证据理解，然后才进入浏览器提案。
    assert calls==(['understand','understand','select_upload','browser'] if choice=='upload_accept' else ['understand','understand','browser'])
    assert len(store.runs(session))==1
    record=store.run(window.run_id)
    assert json.loads(record['result'])['status']=='needs_input'
    assert 'Which announcement?' in window.transcript.toPlainText()
    assert window.browser_panel is not None
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.conversation_state import ConversationState
    pending_question=ConversationState(store).read(session)
    assert pending_question['question']['text']=='Which announcement?'
    reply=AgentController(store).prepare(session,'The second one',model_id='m',selected_ids=[],browser_enabled=True)
    assert [m.text for m in reply.request.context]==['打开https://example.com并查看公告','Which announcement?']
    assert len(store.runs(session))==1  # Answering cannot itself authorize another browser run.
else:
    assert calls==(['understand','understand','select_upload'] if choice=='upload_decline' else ['understand','understand']) and store.runs(session)==[]
    assert window.browser_panel is None
window.client=None; window.close(); qt.processEvents()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path), choice],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
