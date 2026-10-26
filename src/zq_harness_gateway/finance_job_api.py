"""Additive finance job routes; platform users and workers have separate auth."""
import hashlib,json,secrets
from fastapi import Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool
from .finance_jobs import JobQueue,JobError
from asset_based_agent.finance_data import QueryError

def install_finance_jobs(app,engine,authenticate,node_hashes,*,cipher=None):
    queue=JobQueue(engine,cipher if cipher is not None else app.state.finance_service.cipher)
    def owner(request):
        with app.state.session_factory() as db:return authenticate(db,request)
    def node(request):
        header=request.headers.get('authorization','')
        if not header.startswith('Bearer '):raise JobError('NODE_UNAUTHORIZED')
        actual=hashlib.sha256(header[7:].encode()).hexdigest()
        for name,digest in node_hashes.items():
            if secrets.compare_digest(actual,digest):return name
        raise JobError('NODE_UNAUTHORIZED')
    async def body(request,limit=65536):
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>limit:raise JobError('PAYLOAD_TOO_LARGE')
        try:value=json.loads(raw)
        except ValueError:raise JobError('INVALID_JSON') from None
        if not isinstance(value,dict):raise JobError('INVALID_JSON')
        return value
    def fields(value,required):
        if set(value)!=set(required):raise JobError('INVALID_FIELDS')
    async def invoke(operation):
        try:
            await run_in_threadpool(queue.sweep)
            return await operation()
        except QueryError:
            return JSONResponse({'error':{'code':'INVALID_ARGUMENTS'}},status_code=422)
        except JobError as error:
            code=str(error);status=401 if code=='NODE_UNAUTHORIZED' else 404 if code=='NOT_FOUND' else 413 if code in ('PAYLOAD_TOO_LARGE','RESULT_TOO_LARGE') else 409 if code in ('STALE_LEASE','IDEMPOTENCY_CONFLICT','QUEUE_FULL') else 422
            return JSONResponse({'error':{'code':code}},status_code=status)
    @app.post('/api/v1/harness/finance/jobs')
    async def submit(request:Request):
        async def operation():
            user=await run_in_threadpool(owner,request);value=await body(request)
            fields(value,['request_id','tool','arguments'])
            if not isinstance(value['request_id'],str) or not isinstance(value['tool'],str) or not isinstance(value['arguments'],dict):raise JobError('INVALID_FIELDS')
            try:return await run_in_threadpool(queue.submit,str(user),value['request_id'],value['tool'],value['arguments'])
            except (TypeError,ValueError):raise JobError('INVALID_ARGUMENTS') from None
        return await invoke(operation)
    @app.get('/api/v1/harness/finance/jobs/{identifier}')
    async def get(identifier:str,request:Request):
        async def operation():
            user=await run_in_threadpool(owner,request)
            return await run_in_threadpool(queue.get,str(user),identifier)
        return await invoke(operation)
    @app.post('/api/v1/harness/finance/jobs/{identifier}/cancel')
    async def cancel(identifier:str,request:Request):
        async def operation():
            user=await run_in_threadpool(owner,request)
            return await run_in_threadpool(queue.cancel,str(user),identifier)
        return await invoke(operation)
    @app.get('/api/v1/harness/finance/jobs/{identifier}/result')
    async def download(identifier:str,request:Request):
        async def operation():
            user=await run_in_threadpool(owner,request)
            value=await run_in_threadpool(queue.download,str(user),identifier)
            return Response(value,media_type='application/json',headers={'Cache-Control':'no-store'})
        return await invoke(operation)
    @app.post('/api/v1/harness/finance/node/claim')
    async def claim(request:Request):
        async def operation():
            identity=node(request)
            return {'job':await run_in_threadpool(queue.claim,identity)}
        return await invoke(operation)
    @app.post('/api/v1/harness/finance/node/{identifier}/{action}')
    async def complete(identifier:str,action:str,request:Request):
        async def operation():
            identity=node(request);value=await body(request,65*1024*1024)
            if action=='heartbeat':
                fields(value,['lease'])
                if not isinstance(value['lease'],str):raise JobError('INVALID_FIELDS')
                return await run_in_threadpool(queue.heartbeat,identity,identifier,value['lease'])
            if action=='result':
                fields(value,['lease','result'])
                if not isinstance(value['lease'],str):raise JobError('INVALID_FIELDS')
                return await run_in_threadpool(queue.finish,identity,identifier,value['lease'],value['result'])
            raise JobError('NOT_FOUND')
        return await invoke(operation)
    return queue
