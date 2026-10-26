"""In-server queue consumer: no desktop relay, no inbound node credential."""
import asyncio,contextlib,importlib.util,json,os,sys,time,uuid
from pathlib import Path
from .official_sdk import request_for

class ServerFinanceWorker:
    def __init__(self,queue):
        self.queue=queue;self.last_error=None;self.verified_at=None
    def configured(self):return bool(os.environ.get('IFIND_USERNAME') and os.environ.get('IFIND_PASSWORD'))
    def health(self):
        return {**self.queue.health(),'configured':self.configured(),'execution_location':'server',
                'desktop_relay_required':False,'live_access_verified':self.verified_at is not None,
                'last_success_at':self.verified_at,'last_error':self.last_error}
    async def query(self,job):
        request=request_for(job['tool'],job['arguments'])
        env=os.environ.copy()
        spec=importlib.util.find_spec('iFinDAPI')
        if spec is not None:
            libs=Path(spec.origin).parent/'Linux/bin64'
            env['LD_LIBRARY_PATH']=str(libs)+':'+env.get('LD_LIBRARY_PATH','')
        proc=await asyncio.create_subprocess_exec(sys.executable,'-B','-m','zq_harness_gateway.official_sdk',
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
        communication=asyncio.create_task(proc.communicate(json.dumps(request).encode()))
        start=time.monotonic()
        try:
            while not communication.done():
                await asyncio.wait({communication},timeout=5)
                state=await asyncio.to_thread(self.queue.heartbeat,'server-sdk',job['id'],job['lease'])
                if state['status']=='cancel_requested':return {'status':'cancelled'}
                if time.monotonic()-start>60:return {'status':'timeout','errorcode':'SDK_TIMEOUT'}
            out,_=await communication
            if len(out)>64*1024*1024:return {'status':'failed','errorcode':'RESULT_TOO_LARGE'}
            result=json.loads(out)
            if not isinstance(result,dict):raise ValueError('INVALID_RESULT')
            return result
        finally:
            if proc.returncode is None:proc.kill()
            await communication
    async def once(self):
        await asyncio.to_thread(self.queue.sweep)
        if not self.configured():
            self.last_error='SERVER_IFIND_CREDENTIALS_MISSING';return False
        job=await asyncio.to_thread(self.queue.claim,'server-sdk')
        if not job:return False
        try:result=await self.query(job)
        except asyncio.CancelledError:raise
        except Exception:result={'status':'failed','errorcode':'SERVER_SDK_ERROR'}
        result['source']='official_ifind'
        await asyncio.to_thread(self.queue.finish,'server-sdk',job['id'],job['lease'],result)
        if result.get('status')=='ok':self.verified_at=time.time();self.last_error=None
        else:self.last_error=result.get('errorcode',result.get('status'))
        return True
    async def loop(self):
        while True:
            try:worked=await self.once()
            except asyncio.CancelledError:raise
            except Exception:self.last_error='SERVER_QUEUE_ERROR';worked=False
            await asyncio.sleep(.2 if worked else 3)

def install_server_worker(app,queue):
    worker=ServerFinanceWorker(queue);old=app.router.lifespan_context
    @contextlib.asynccontextmanager
    async def lifespan(application):
        async with old(application) as state:
            if worker.configured():
                # One bounded startup acceptance query. Results retain queue
                # encryption/ownership; public health exposes only success.
                await asyncio.to_thread(queue.submit,'_server_healthcheck',uuid.uuid4().hex,
                    'fuyao_ifind_history',{'codes':'600519.SH','indicators':'close',
                    'start_date':'2026-01-30','end_date':'2026-01-30'})
            task=asyncio.create_task(worker.loop())
            try:yield state
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await task
    app.router.lifespan_context=lifespan
    app.state.official_server_worker=worker
    return worker
