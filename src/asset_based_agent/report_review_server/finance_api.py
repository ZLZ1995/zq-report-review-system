"""Finance routes reuse existing login, administrator and model billing services."""
from fastapi import Depends, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..finance_data import tools
from .services.auth_service import ServiceError
from .services.finance_service import FinanceService


class FinanceQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict = Field(default_factory=dict)


class FinanceAsk(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    model_id: str = Field(min_length=1, max_length=36)
    prompt: str = Field(min_length=1, max_length=12000)
    context: list[str] = Field(default_factory=list, max_length=6)


class FinanceKey(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_key: SecretStr = Field(min_length=1, max_length=4096)


def register_finance_routes(app, get_context, get_db):
    service = FinanceService(app.state.settings, app.state.review_job_service.metered)
    app.state.finance_service = service
    auth, database = Depends(get_context), Depends(get_db)

    def active(context=auth):
        if context.user.must_change_password:
            raise ServiceError('password_change_required', '请先修改临时密码。', 403)
        return context

    def admin(context=auth):
        app.state.auth_service.require_admin(context)
        return active(context)

    authorized, administrator = Depends(active), Depends(admin)

    @app.get('/api/v1/admin/finance/credential')
    def credential_status(response: Response, _context=administrator, db=database):
        response.headers['Cache-Control'] = 'no-store'
        return service.credential_status(db)

    @app.put('/api/v1/admin/finance/credential')
    def configure(payload: FinanceKey, response: Response, context=administrator, db=database):
        response.headers['Cache-Control'] = 'no-store'
        return service.configure(db, context.user.user_id, payload.api_key.get_secret_value())

    @app.get('/api/v1/finance/tools')
    def catalog(_context=authorized):
        return {'schema_version': 1, 'tools': list(tools().values())}

    @app.post('/api/v1/finance/query')
    def query(payload: FinanceQuery, response: Response, _context=authorized, db=database):
        response.headers['Cache-Control'] = 'no-store'
        return service.query(db, payload.tool, payload.arguments, user_id=_context.user.user_id)

    @app.post('/api/v1/finance/ask')
    def ask(payload: FinanceAsk, response: Response, context=authorized, db=database):
        response.headers['Cache-Control'] = 'no-store'
        if sum(len(c) for c in payload.context) > 12000:
            raise ServiceError('finance_context_limit', '查询历史过长，请缩小范围。', 422)
        return service.ask(db, context.user.user_id, payload)

    @app.get('/api/v1/finance/requests/{request_id}')
    def result(request_id: str, response: Response, context=authorized, db=database):
        response.headers['Cache-Control'] = 'no-store'
        return service.result(db, context.user.user_id, request_id)

    @app.post('/api/v1/finance/requests/{request_id}/cancel')
    def cancel(request_id: str, context=authorized, db=database):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}', request_id):
            raise ServiceError('finance_request_invalid', '查询编号无效。', 422)
        return service.cancel(db, context.user.user_id, request_id)
