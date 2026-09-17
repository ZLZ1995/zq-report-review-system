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

from ..agent_contracts import (
    PlanningRequest,
    PlanProposal,
    TaskUnderstanding,
    UnderstandingRequest,
)
from ..browser_contracts import BrowserStepProposal, BrowserStepRequest
from .config import ServerSettings
from .crypto import SecretCipher
from .database import Base, build_engine, build_session_factory
from .schemas import (
    BalanceAdjustmentRequest,
    BalanceResponse,
    BillingMultiplierRequest,
    ChangePasswordRequest,
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
        }
        return {'schema_version': 1, 'protocol_version': 1,
                'build_sha': actual_settings.build_sha,
                'capabilities': {name: 1 for name, route in supported.items() if route in routes}}

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
