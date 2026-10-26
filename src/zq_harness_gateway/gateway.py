"""Harness transport extension; all authorization and settlement use the existing service."""
import json
import math
import hashlib
from pathlib import Path
import re
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy import event, select
from asset_based_agent.report_review_server.models import BillingRequest, ModelDefinition
from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.provider_gateway import NormalizedUsage


def validate_payload(payload):
    """Validate the supported OpenAI text/tool envelope before reserving any money."""
    def invalid():
        raise ServiceError('invalid_payload', 'Unsupported payload', 422)
    allowed = {'messages', 'tools', 'max_tokens', 'temperature', 'stop', 'stream'}
    if not isinstance(payload, dict) or set(payload) - allowed or payload.get('stream') is not False:
        invalid()
    messages = payload.get('messages')
    if not isinstance(messages, list) or not messages or len(messages) > 2000:
        invalid()
    pending = set()
    used = set()
    for message in messages:
        if not isinstance(message, dict) or set(message) - {'role', 'content', 'reasoning_content', 'tool_calls', 'tool_call_id'}:
            invalid()
        role = message.get('role')
        if role not in {'system', 'user', 'assistant', 'tool'}:
            invalid()
        content = message.get('content')
        calls = message.get('tool_calls')
        if not isinstance(content, str) and not (role == 'assistant' and content is None and calls):
            invalid()
        if isinstance(content, str) and len(content) > 200000:
            invalid()
        if 'reasoning_content' in message and (role != 'assistant' or not isinstance(message['reasoning_content'], str)):
            invalid()
        if role == 'tool':
            call_id = message.get('tool_call_id')
            if not isinstance(call_id, str) or call_id not in pending or calls is not None:
                invalid()
            pending.remove(call_id)
        else:
            if pending or 'tool_call_id' in message:
                invalid()
        if calls is not None:
            if role != 'assistant' or not isinstance(calls, list) or not calls or len(calls) > 128:
                invalid()
            for call in calls:
                if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function':
                    invalid()
                call_id, function = call['id'], call['function']
                if not isinstance(call_id, str) or not 1 <= len(call_id) <= 512 or call_id in used or \
                        not isinstance(function, dict) or set(function) != {'name', 'arguments'} or \
                        not isinstance(function['name'], str) or not 1 <= len(function['name']) <= 128 or \
                        not isinstance(function['arguments'], str):
                    invalid()
                try:
                    arguments = json.loads(function['arguments'])
                except (ValueError, RecursionError):
                    invalid()
                if not isinstance(arguments, dict):
                    invalid()
                used.add(call_id); pending.add(call_id)
    if pending:
        invalid()
    tools = payload.get('tools', [])
    if not isinstance(tools, list) or len(tools) > 256:
        invalid()
    names = set()
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) != {'type', 'function'} or tool['type'] != 'function':
            invalid()
        function = tool['function']
        if not isinstance(function, dict) or set(function) - {'name', 'description', 'parameters'}:
            invalid()
        name = function.get('name')
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or name in names or \
                not isinstance(function.get('parameters'), dict) or not isinstance(function.get('description', ''), str):
            invalid()
        names.add(name)
    if 'temperature' in payload and (type(payload['temperature']) not in (int, float) or \
            not math.isfinite(payload['temperature']) or not 0 <= payload['temperature'] <= 2):
        invalid()
    if 'stop' in payload:
        stop = payload['stop']
        if not isinstance(stop, str) and not (isinstance(stop, list) and 1 <= len(stop) <= 4 and all(isinstance(x, str) for x in stop)):
            invalid()


def install_gateway(app, service):
    if getattr(app.state, 'zq_harness_gateway_installed', False):
        return
    engine = app.state.session_factory.kw['bind']
    if engine.dialect.name == 'sqlite' and not getattr(engine, '_zq_serialized_transactions', False):
        # SQLite ignores SELECT FOR UPDATE used by the original wallet service.
        # Reserve a writer at transaction start so concurrent settlements cannot overwrite balances.
        @event.listens_for(engine, 'begin')
        def begin_sqlite_transaction(connection):
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        engine._zq_serialized_transactions = True

    def authenticate(db, authorization, expected_account=None, *, ready=False):
        if not authorization.startswith("Bearer "):
            raise ServiceError("authentication_required", "Login required", 401)
        context = app.state.auth_service.authenticate_access(db, authorization[7:])
        user_id = context.user.user_id
        if expected_account is not None and expected_account != user_id:
            raise ServiceError("profile_account_mismatch", "Profile account mismatch", 403)
        if ready and context.user.must_change_password:
            raise ServiceError('password_change_required', 'Password change required', 403)
        return user_id

    def finance_user(db, request):
        authorization = request.headers.get('authorization', '')
        return authenticate(db, authorization, request.headers.get('x-zq-account-id'), ready=True)

    @app.get('/api/v1/harness/capabilities')
    def harness_capabilities():
        return {'schema_version': 1, 'protocol_version': 1,
                'extension_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'capabilities': {'completions': 1, 'request_reconciliation': 1, 'account': 1, 'finance': 1,
                    'official_finance_jobs': int(getattr(app.state,'finance_jobs',None) is not None)},
                'official_node_online': app.state.finance_jobs.health()['node_online'] if getattr(app.state,'finance_jobs',None) is not None else False,
                'official_execution_location':'server', 'desktop_relay_required':False,
                'official_runtime_version':3,
                'official_server_configured':app.state.official_server_worker.configured() if getattr(app.state,'official_server_worker',None) else False,
                'official_server_sdk_verified':app.state.official_server_worker.verified_at is not None if getattr(app.state,'official_server_worker',None) else False,
                'official_server_error':app.state.official_server_worker.last_error if getattr(app.state,'official_server_worker',None) else None}

    @app.get('/api/v1/harness/finance/tools')
    def finance_catalog(request: Request):
        from asset_based_agent.finance_data import tools
        with app.state.session_factory() as db:
            finance_user(db, request)
            return {'tools': list(tools().values())}

    @app.post('/api/v1/harness/finance/query')
    async def finance_query(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise ServiceError('finance_payload_too_large', 'Query too large', 413)
        try:
            from asset_based_agent.report_review_server.finance_api import FinanceQuery
            query = FinanceQuery.model_validate_json(body)
        except ValueError:
            raise ServiceError('finance_invalid_query', 'Invalid query', 422) from None
        def execute_query():
            with app.state.session_factory() as db:
                user_id=finance_user(db, request)
                if query.tool != 'fuyao_ifind_status' or getattr(app.state, 'finance_jobs', None) is None:
                    return app.state.finance_service.query(db, query.tool, query.arguments, user_id=user_id)
            return {'tool':query.tool,'parameters':query.arguments,'status':'succeeded',
                    'provider':'official_ifind','data':app.state.official_server_worker.health()}
        return await run_in_threadpool(execute_query)

    @app.get('/api/v1/harness/account')
    def account_snapshot(request: Request):
        with app.state.session_factory() as db:
            user_id = authenticate(db, request.headers.get('authorization', ''),
                                   request.headers.get('x-zq-account-id'))
            wallet = app.state.wallet_service.get_wallet(db, user_id)
            models = app.state.model_admin_service.list_public_models(db)
            return {'account_id': user_id, 'balance': format(wallet.balance, 'f'), 'currency': wallet.currency,
                    'models': [{'id': model.model_id, 'name': model.display_name} for model in models]}

    def execute(authorization, data, expected_account=None):
        if not isinstance(data, dict) or set(data) != {"request_id", "model_id", "payload"}:
            raise ServiceError("invalid_request", "Invalid request", 422)
        request_id, model_id, payload = data["request_id"], data["model_id"], data["payload"]
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
            raise ServiceError("invalid_request_id", "Invalid request ID", 422)
        if not isinstance(model_id, str) or not isinstance(payload, dict):
            raise ServiceError("invalid_request", "Invalid request", 422)
        validate_payload(payload)
        with app.state.session_factory() as db:
            user_id = authenticate(db, authorization, expected_account, ready=True)
            model = db.get(ModelDefinition, model_id)
            if model is None:
                raise ServiceError("model_not_found", "Unknown model", 404)
            maximum = payload.get("max_tokens")
            if type(maximum) is not int or maximum < 1 or maximum > model.max_output_tokens:
                raise ServiceError("invalid_max_tokens", "Invalid output limit", 422)
            # Conservative byte upper bound, not a claim of exact token estimation.
            estimate = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            result = service.execute(db, user_id=user_id, model_id=model_id,
                client_request_id=request_id,
                estimated_usage=NormalizedUsage(input_tokens=estimate, output_tokens=maximum), payload=payload)
            return {"response": result.payload, "request_id": request_id,
                    "billing_request_id": result.billing_request_id, "charged_amount": format(result.charged_amount, 'f')}

    @app.post("/api/v1/harness/completions")
    async def completion(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise ServiceError("payload_too_large", "Request too large", 413)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise ServiceError("invalid_json", "Invalid JSON", 422)
        # Provider IO and SQLite work must not block health, logout or other users.
        return await run_in_threadpool(execute, request.headers.get("authorization", ""), data,
                                       request.headers.get("x-zq-account-id"))

    @app.get("/api/v1/harness/requests/{request_id}")
    def receipt(request_id: str, request: Request):
        with app.state.session_factory() as db:
            user_id = authenticate(db, request.headers.get("authorization", ""),
                                   request.headers.get("x-zq-account-id"))
            row = db.scalar(select(BillingRequest).where(BillingRequest.user_id == user_id,
                BillingRequest.client_request_id == request_id))
            if row is None:
                raise ServiceError("request_not_found", "Unknown request", 404)
            return {"request_id": row.client_request_id, "status": row.status,
                    "billing_request_id": row.billing_request_id,
                    "charged_amount": format(row.charged_amount, 'f'), "error_code": row.error_code}
    import os
    if os.environ.get('ZQ_FINANCE_JOBS_ENABLED', '1') == '1':
        from .finance_job_api import install_finance_jobs
        from .server_finance_worker import install_server_worker
        # Empty node authorization permanently rejects the former desktop relay.
        app.state.finance_jobs = install_finance_jobs(app, engine, finance_user, {})
        app.state.finance_service.official_queue = app.state.finance_jobs
        worker=install_server_worker(app,app.state.finance_jobs)
        app.state.finance_service.official_health=worker.health
    app.state.zq_harness_gateway_installed = True
