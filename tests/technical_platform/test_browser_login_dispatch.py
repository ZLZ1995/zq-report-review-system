import os
import subprocess
import sys


def test_login_dispatch_is_native_scoped_and_cancel_safe():
    code = r'''
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication
from test_browser_observer import bound, respond
from asset_based_agent.agent_contracts import BrowserIntent
from asset_based_agent.browser_contracts import BrowserStepProposal
from asset_based_agent.technical_platform.browser_execution_loop import BrowserExecutionLoop
app=QCoreApplication([])
for scenario in ('normal','unavailable','navigation','cancel','unknown'):
    observer, leases, lease, page, _=bound()
    observed=[]; observer.observe(lease, observed.append); respond(page)
    class Login:
        callback=None
        closed=False
        def fill(self, callback): self.callback=callback
        def close(self): self.closed=True
    login=Login()
    loop=BrowserExecutionLoop(None,observer,None,leases,lease,task_id='t',model_id='m',goal='Login',
        scope=BrowserIntent(origins=['https://example.com'],actions=['observe','login']),
        authorized=lambda:True,login=None if scenario=='unavailable' else login)
    loop._running=True
    finished=[]; loop.finished.connect(lambda status,_:finished.append(status))
    if scenario=='navigation': page.urlChanged.emit()
    loop._dispatch(SimpleNamespace(observation=observed[0]),
        BrowserStepProposal(request_id='r',action='login',summary='Local login'))
    if scenario in ('unavailable','navigation'):
        assert login.callback is None and finished==['needs_input' if scenario=='unavailable' else 'unknown']
    else:
        assert login.callback is not None and not finished
        if scenario=='cancel': loop.stop()
        login.callback('unknown' if scenario=='unknown' else 'dispatched')
        app.processEvents()
        if scenario=='normal':
            assert len(page.calls)==2 and not finished
            loop.stop()
        assert finished==['unknown' if scenario=='unknown' else 'cancelled']
        assert login.closed
    observer.close(); leases.close()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
