"""FastAPI composition root for the report-review control plane."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

try:
    from ..agent_contracts import PlanningRequest, PlanProposal, TaskUnderstanding, UnderstandingRequest
    from ..browser_contracts import BrowserStepProposal, BrowserStepRequest
except ModuleNotFoundError:  # pragma: no cover - legacy Zeabur build context
    import base64
    import sys
    import types
    import zlib
    for _name, _payload in (
        ('asset_based_agent.agent_contracts', "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"),
        ('asset_based_agent.browser_contracts', "eNq9WVlz48YRfuevmCipAuBouZRWq1orZio+U65yOa69/LCSWUNgSI4FYpCZASV6rf+e7jlwDkmsU2U9iOQc3V/f3cDZ2dmbDZUsI0spHhSTpJSiFIrm6oZkVFMiinx/TgpBNkJpkoqMESEJe2RppbkoCK30Rkiu99Ozs7PJSoot0fuSF2vCt6WQmvzANZM0t1uVzHO+nJZUKuYPwJoqc64n9ki5z2iheeq3v+Msz87JFjjnC0DIac5/Y9Kv7OAnABXSXZ/SNSv0IhWFljTVypP5ysr3faFh+5x8n8EHX3Ek9JqlQgKL90wqEIllk8kkzalS5OuN4CmL7YHkZkLgj2c3RGlJ5hZZXFINAhZzGf3y4eLZ53cfZvDv4+z88ulvUWJuaPaou3e29HGRs2KtN/OL61nS8EPUIv9/Gd7zAu44xX+IlpXWoojOSZTz4h4/EdEKieEPxXKWavy24jmL7kZixlMZV3SZM2C2FCI3S6JEtwDvybnSH6wC72oiGVvRKteLFZhGyP0cD4ElW6RnLXW8pg//WYLRdhRpdrVSiCJlPYS8qMl0iV6+snjBUde8OCjX5ezq1RiTXc5mTgGpNVgtrv15Fybu7mhZFSnVtda8tB1RO5I7kUtw7cXOOukN4YWu2azZfHaOcHmq529lxSynCtBUynDyzoCbCA8/a87fiIciFzR7U223VO57iqbb0Xp+BSja7vnL89vb28fZ7O7v3jUVxO4o7KNM5QV4VyL8LyVENDjWMHyaaP8TRcrZ/PqKfEYuZpf+IyCn2tDLl9eHIxyCmz5b3X28vjLh7SV26eyNZuVr9t+KKR3X6csJLu36IqAAmzoDG5qq+9C6Qlom4HpyXhg5X1wGJFsLmo8O0DqiVCpKYNNJ19Yhmni4accK+Z38CFIDE/xwUbktcwZ+v8icZ/sA7Xn6JySmF5dOKlZAIPVoYxz3Sc2/gyLKQlFpnHVBnbd6aF0f/kRkhvC/+jUyxoV59CBp6XwViIG91jTdL8DxShZD8l+dkw0tspxJ5zjmINb+ud8wx5J6k68g/WqCi9OQruuDntK0FGUcBY5C1UGrhUmHVH2AdODoUdIDGxyg2z83ICqZrmRhbnSMULclzgZ0BRHdMsJSVEXGMqvYmzbGQ6ITMAWJ/M/IyMILe9wEzRQAmtLbkUVSDq3We5pX7FspAU/0b0+beGJEVFpx6Oww/G0ERskAU18XBpBX0RE8HTg2tYMPFvFHOuUZWcEvWl/s83hKyF/m5nRwO0lOCWujivgbJtRqcQ1MhEO3S76uRKUCYge81kk+whYh2Wmxj6Eab6e2xAUu2w1ldIMn6+0AltMq8DmPKJv0Tlq7CUDI4FPMX2WceKuZDevjWbUtF78qaFeSKRQHWANv0Ktnr6IkIf8k11eQ1E+Bc3neFysYLFLGQMMmPkLmaJUBwpXBihHZ5RM4fFLbNwNbDdG2y46jd1SZ7RYRsukAk9/rgzfhkfrwSBGwP9pEhF9JxiD/BkKHY9fp6ihEv6ZyzbTqwQXu6KAGgfAIhEEwdb19C4JfSoZA/ygsRzEa5FjUXqj/+clNrJ/SANnwbM1IBd3xNeDAMchBwa8poLt3o1HeHZZUClKatQfKzUouwCHwS50Y4LtLj/ANHMRSKrja+DHL2KDbJfn+IYq6Zd4qZIfaG3Xhqu6pYMIedaOZf1yqGNm+Nd0b20EsDAazg+z8NZ+eF/1Z98DNZqBb/grmWOR0ycaJ+PLiT++WMDLu2R5jI45aklpXa/BHySCJYbIyzQg4SQw0AjFV9yqwfbQ5maA0ri1hC/e4ZwHTYRm7QDmvH/50AwgkG44b006fwzyNVmmIE4vEE+2S8VHbp1N219uEQCH1bhPbmIs889YqKB21V19wHu3LWaPIwzWpBs5N8tB7suVqS3W6cf5hswjIVXOxKx6t35/XaaDT6TWytrzCF6hed+QlHDRIoQ6jI3jbxdrFHLM8TMlxmpAvyIvLJoEHb47utBAolwx6JNNrsVbvhV0Te8SEz7WLXKdIlrdt29aGkGE8x+z3rgAucBJ4W3WRLdMUoyBKeqbxyu4l5yeDtXvGW+BAr33YjRyZg41CAM3JamMB1pqxRWGcSvyDXnNnAAF91dYxw8EL3eu6uh3XkN0bipXc0Gk7RFpJCZHUHuUHAIz8fWk7YTMKUxjXe84ePKNRuIbKcdAC+m/MV5W+C2hDP6AqQ69Bg48ydgDTPLTOYCk9Csfox84jnag3iKZcUZVybgM+uJ9BE6vjZJBFDmSVi9mMfDHHh0Bxl1SCyy+xoJ8S+GdATLYVlJUlM/S0MBchueaQMRj0j3Xj38gKSb7p0brKx+5mnOs7Akjv3esfDoffka4v0Nr1YtG1dJ8WjPZSMBprqRuS5vVJBnXHvzqJ28rouErXK2DXZFRzf1oBZ3wU2p6jWtsl9NkPUCHa26FqE93eRp264bhggYEZRqmSpsy64PF608HeYrCKPjpIKt2wLXu6ef7crxRM5yJ9isJZ2o12J33yx8YxRqTpP+IjDYJ60JmHMll9zHoEHAJn0XGcNvryBOrpEaGZYXE+77th4lpCPFIzZjmI37Em7Dp+LpGi2u3KtH7Hc0KHby0BClwwlcr65VA3d8Ut17Y6NOHjmOGbqyYOey+ugr1Oi1zzPKZPEbOHIRHMc9TxrHvYQ0/f2iSRocOXnMDln5CFUJlXbifuGw8L3m7e450g4ZzTFoo+Fbc5OZD3D1S57sMBR7N+QnAy5L604DLBbHYxfXXjo863gxnRNWlWmCPdwKDo+enUt8GTkzVvcLWfZ9pPc9AaRweLr+3jO4RYzxY5Te9VKzYdHyf4X8m3O1ZAi7KW9oExscKjiPhmHnZqiOTthtm39DuYacEtFNEbm8gi5aiBFitguqwUL5gCr05TVmqKgqUSn4Vw+g8M3BKtwbLn6LjMVgAGVImq4IJS00lrvPQAJv8DmI9cMw=="),
    ):
        _module = types.ModuleType(_name)
        _module.__package__ = 'asset_based_agent'
        exec(zlib.decompress(base64.b64decode(_payload)), _module.__dict__)
        sys.modules[_name] = _module
    from ..agent_contracts import PlanningRequest, PlanProposal, TaskUnderstanding, UnderstandingRequest
    from ..browser_contracts import BrowserStepProposal, BrowserStepRequest
from .config import ServerSettings
from .crypto import SecretCipher
from .database import Base, build_engine, build_session_factory
from .schemas import (
    BalanceAdjustmentRequest,
    BalanceResponse,
    BillingMultiplierRequest,
    ChangePasswordRequest,
    ClientReleaseCreateRequest,
    ClientReleaseResponse,
    ClientReleaseTransitionRequest,
    CreateUserRequest,
    LoginRequest,
    ModelAdminResponse,
    ModelCreateRequest,
    ProviderRouteCreateRequest,
    ProviderRouteResponse,
    PublicModelResponse,
    RefreshRequest,
    ResetPasswordRequest,
    ReviewJobCreateRequest,
    ReviewJobResponse,
    TokenResponse,
    UserResponse,
)
from .services.auth_service import AuthContext, AuthService, ServiceError
from .services.client_release_service import ClientReleaseService
from .services.browser_step import propose_browser_step
from .services.material_analysis import MaterialPlan, MaterialRequest, analyze_materials
from .services.model_admin_service import ModelAdminService
from .services.provider_gateway import HttpProviderClient
from .services.review_job_service import ReviewJobService
from .services.skill_routing import RoutePlan, RouteRequest, route_skill
from .services.task_planning import propose_plan
from .services.task_understanding import understand_task
from .services.temporary_data_cleanup import cleanup_expired_temporary_data
from .services.wallet_service import WalletService, display_money

_BEARER = HTTPBearer(auto_error=False)
_LOGGER = logging.getLogger(__name__)


def create_app(
    settings: ServerSettings | None = None,
    *,
    engine: Engine | None = None,
) -> FastAPI:
    actual_settings = settings or ServerSettings.from_environment()
    actual_engine = engine or build_engine(actual_settings.database_url)
    session_factory = build_session_factory(actual_engine)
    if actual_settings.environment in {"development", "test"}:
        Base.metadata.create_all(actual_engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with session_factory() as cleanup_db:
            cleanup_expired_temporary_data(cleanup_db)
        cleanup_task = asyncio.create_task(_temporary_cleanup_loop(session_factory))
        try:
            yield
        finally:
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task

    app = FastAPI(
        title="ZQ Report Review Control API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = actual_settings

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(_request: Request, _exc: RequestValidationError):
        # Never echo rejected passwords, API keys, or nested request payloads.
        return JSONResponse(status_code=422, content={
            "error": {"code": "invalid_request", "message": "输入格式不正确，请核对必填项和取值范围。"},
        })
    app.state.engine = actual_engine
    app.state.session_factory = session_factory
    app.state.auth_service = AuthService(actual_settings)
    app.state.wallet_service = WalletService()
    app.state.client_release_service = ClientReleaseService()
    app.state.model_admin_service = ModelAdminService(
        SecretCipher(actual_settings.encryption_key_bytes())
    )
    app.state.review_job_service = ReviewJobService(
        actual_settings,
        HttpProviderClient(SecretCipher(actual_settings.encryption_key_bytes())),
    )

    @app.exception_handler(ServiceError)
    async def handle_service_error(
        _request: Request,
        exc: ServiceError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    def get_db(request: Request) -> Iterator[Session]:
        with request.app.state.session_factory() as db:
            yield db

    def get_context(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),
        db: Session = Depends(get_db),
    ) -> AuthContext:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise ServiceError("authentication_required", "需要登录。", 401)
        return request.app.state.auth_service.authenticate_access(db, credentials.credentials)

    @app.get("/api/v1/health")
    def health(db: Session = Depends(get_db)) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "report-review-server"}

    @app.get('/api/v1/capabilities')
    def capabilities():
        # Advertise protocol support, not provider availability or authorization.
        # No credentials, prices, database addresses or deployment environment.
        routes = {(route.path, method) for route in app.routes
                  for method in getattr(route, 'methods', ())}
        supported = {
            'skill_routing': ('/api/v1/skill-route', 'POST'),
            'task_understanding': ('/api/v1/agent/understand', 'POST'),
            'task_planning': ('/api/v1/agent/plan', 'POST'),
            'browser_step': ('/api/v1/agent/browser-step', 'POST'),
            'browser_view_actions': ('/api/v1/agent/browser-step', 'POST'),
            'browser_saved_login': ('/api/v1/agent/browser-step', 'POST'),
            'browser_download': ('/api/v1/agent/browser-step', 'POST'),
            'browser_generated_download': ('/api/v1/agent/browser-step', 'POST'),
            'browser_upload': ('/api/v1/agent/browser-step', 'POST'),
            'material_analysis': ('/api/v1/material-analysis', 'POST'),
            'review_jobs': ('/api/v1/review-jobs', 'POST'),
            'review_cancel': ('/api/v1/review-jobs/{job_id}/cancel', 'POST'),
            'client_release': ('/api/v1/client-releases/current', 'GET'),
        }
        return {'schema_version': 1, 'protocol_version': 1,
                'build_sha': actual_settings.build_sha,
                'capabilities': {name: 1 for name, route in supported.items() if route in routes}}

    @app.get('/api/v1/client-releases/current')
    def current_client_release(channel: str = 'stable'):
        with session_factory() as db:
            return app.state.client_release_service.current(db, channel=channel)

    @app.post('/api/v1/admin/client-releases', response_model=ClientReleaseResponse, status_code=201)
    def create_client_release(payload: ClientReleaseCreateRequest, request: Request,
                              context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        request.app.state.auth_service.require_admin(context)
        return request.app.state.client_release_service.create(db, admin_user_id=context.user.user_id, manifest=payload.manifest)

    @app.post('/api/v1/admin/client-releases/{release_id}/transition', response_model=ClientReleaseResponse)
    def transition_client_release(release_id: str, payload: ClientReleaseTransitionRequest, request: Request,
                                  context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        request.app.state.auth_service.require_admin(context)
        return request.app.state.client_release_service.transition(db, admin_user_id=context.user.user_id,
                                                                    release_id=release_id, status=payload.status)

    @app.post("/api/v1/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
        return request.app.state.auth_service.login(
            db,
            username=payload.username,
            password=payload.password,
            client_instance_id=payload.client_instance_id,
        )

    @app.post("/api/v1/auth/refresh", response_model=TokenResponse)
    def refresh(
        payload: RefreshRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        return request.app.state.auth_service.refresh(db, payload.refresh_token)

    @app.post("/api/v1/auth/heartbeat")
    def heartbeat(
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        request.app.state.auth_service.heartbeat(db, context)
        return {
            "status": "ok",
            "server_time": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> Response:
        request.app.state.auth_service.logout(db, context)
        return Response(status_code=204)

    @app.post("/api/v1/auth/change-password", status_code=204)
    def change_password(
        payload: ChangePasswordRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> Response:
        request.app.state.auth_service.change_password(
            db,
            context,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
        return Response(status_code=204)

    @app.post(
        "/api/v1/admin/users",
        response_model=UserResponse,
        status_code=201,
    )
    def create_user(
        payload: CreateUserRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ):
        request.app.state.auth_service.require_admin(context)
        return request.app.state.auth_service.create_user(
            db,
            username=payload.username,
            display_name=payload.display_name,
            temporary_password=payload.temporary_password,
            email=payload.email,
        )

    @app.post("/api/v1/admin/users/{user_id}/reset-password", status_code=204)
    def reset_password(
        user_id: str,
        payload: ResetPasswordRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> Response:
        request.app.state.auth_service.require_admin(context)
        request.app.state.auth_service.reset_password(
            db,
            user_id=user_id,
            temporary_password=payload.temporary_password,
        )
        return Response(status_code=204)

    @app.get("/api/v1/account/balance", response_model=BalanceResponse)
    def account_balance(
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> BalanceResponse:
        wallet = request.app.state.wallet_service.get_wallet(db, context.user.user_id)
        return BalanceResponse(
            balance=display_money(wallet.balance),
            currency=wallet.currency,
        )

    @app.post(
        "/api/v1/admin/users/{user_id}/balance-adjustments",
        response_model=BalanceResponse,
    )
    def adjust_balance(
        user_id: str,
        payload: BalanceAdjustmentRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> BalanceResponse:
        request.app.state.auth_service.require_admin(context)
        wallet = request.app.state.wallet_service.adjust(
            db,
            user_id=user_id,
            amount=payload.amount,
            admin_user_id=context.user.user_id,
        )
        return BalanceResponse(
            balance=display_money(wallet.balance),
            currency=wallet.currency,
        )

    @app.patch(
        "/api/v1/admin/users/{user_id}/billing-multiplier",
        status_code=204,
    )
    def set_billing_multiplier(
        user_id: str,
        payload: BillingMultiplierRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> Response:
        request.app.state.auth_service.require_admin(context)
        request.app.state.model_admin_service.set_user_multiplier(
            db, user_id=user_id, multiplier=payload.multiplier
        )
        return Response(status_code=204)

    @app.get("/api/v1/models", response_model=list[PublicModelResponse])
    def list_models(
        request: Request,
        _context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ):
        return request.app.state.model_admin_service.list_public_models(db)

    @app.post(
        "/api/v1/admin/models",
        response_model=ModelAdminResponse,
        status_code=201,
    )
    def create_model(
        payload: ModelCreateRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ):
        request.app.state.auth_service.require_admin(context)
        return request.app.state.model_admin_service.create_model(
            db,
            code=payload.code,
            display_name=payload.display_name,
            tier=payload.tier,
            model_multiplier=payload.model_multiplier,
            max_output_tokens=payload.max_output_tokens,
        )

    @app.post(
        "/api/v1/admin/models/{model_id}/routes",
        response_model=ProviderRouteResponse,
        status_code=201,
    )
    def create_provider_route(
        model_id: str,
        payload: ProviderRouteCreateRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> ProviderRouteResponse:
        request.app.state.auth_service.require_admin(context)
        route = request.app.state.model_admin_service.create_route(
            db,
            model_id=model_id,
            provider_type=payload.provider_type,
            provider_model=payload.provider_model,
            base_url=payload.base_url,
            api_key=payload.api_key,
            priority=payload.priority,
            timeout_seconds=payload.timeout_seconds,
            rates=payload.rates.model_dump(),
        )
        return ProviderRouteResponse(
            route_id=route.route_id,
            model_id=route.model_id,
            provider_type=route.provider_type,
            provider_model=route.provider_model,
            base_url=route.base_url,
            priority=route.priority,
            enabled=route.enabled,
        )

    @app.post('/api/v1/agent/understand', response_model=TaskUnderstanding)
    def task_understanding(payload: UnderstandingRequest, request: Request,
                           context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        return understand_task(request.app.state.review_job_service.metered, db,
                               context.user.user_id, payload)

    @app.post('/api/v1/agent/plan', response_model=PlanProposal)
    def task_planning(payload: PlanningRequest, request: Request,
                      context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        return propose_plan(request.app.state.review_job_service.metered, db,
                            context.user.user_id, payload)

    @app.post('/api/v1/agent/browser-step', response_model=BrowserStepProposal)
    def browser_step(payload: BrowserStepRequest, request: Request,
                     context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        return propose_browser_step(request.app.state.review_job_service.metered, db, context.user.user_id, payload)

    @app.post('/api/v1/skill-route', response_model=RoutePlan)
    def skill_route(payload: RouteRequest, request: Request,
                    context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        return route_skill(request.app.state.review_job_service.metered, db, context.user.user_id, payload)

    @app.post('/api/v1/material-analysis', response_model=MaterialPlan)
    def material_analysis(payload: MaterialRequest, request: Request,
                          context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        return analyze_materials(request.app.state.review_job_service.metered, db,
                                 context.user.user_id, payload)

    @app.post(
        "/api/v1/review-jobs",
        response_model=ReviewJobResponse,
        status_code=201,
    )
    def create_review_job(
        payload: ReviewJobCreateRequest,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> ReviewJobResponse:
        job = request.app.state.review_job_service.create_job(
            db,
            user_id=context.user.user_id,
            payload=payload,
        )
        return request.app.state.review_job_service.to_response(job)

    @app.post('/api/v1/review-jobs/{job_id}/cancel', response_model=ReviewJobResponse)
    def cancel_review_job(job_id: str, request: Request,
                          context: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
        return request.app.state.review_job_service.cancel_job(db, user_id=context.user.user_id, job_id=job_id)

    @app.post(
        "/api/v1/review-jobs/{job_id}/execute",
        response_model=ReviewJobResponse,
    )
    def execute_review_job(
        job_id: str,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> ReviewJobResponse:
        return request.app.state.review_job_service.execute_job(
            db,
            user_id=context.user.user_id,
            job_id=job_id,
        )

    @app.get(
        "/api/v1/review-jobs/{job_id}",
        response_model=ReviewJobResponse,
    )
    def get_review_job(
        job_id: str,
        request: Request,
        context: AuthContext = Depends(get_context),
        db: Session = Depends(get_db),
    ) -> ReviewJobResponse:
        return request.app.state.review_job_service.get_job(
            db,
            user_id=context.user.user_id,
            job_id=job_id,
        )

    from .admin_web import install_admin_web

    install_admin_web(app, get_context, get_db)
    from .billing_admin_api import register_billing_admin_routes
    register_billing_admin_routes(app, get_context, get_db)
    return app


async def _temporary_cleanup_loop(session_factory) -> None:
    while True:
        await asyncio.sleep(60 * 60)
        try:
            with session_factory() as db:
                cleanup_expired_temporary_data(db)
        except Exception:
            _LOGGER.exception("temporary review data cleanup failed")
