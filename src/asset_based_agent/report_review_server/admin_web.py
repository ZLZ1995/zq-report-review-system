"""Independent control desk assets and explicitly scoped administrative reads."""

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import jwt
from fastapi import Depends, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import ModelDefinition, ProviderRoute, User, Wallet
from .schemas import (
    ModelAdminResponse,
    ProviderRouteResponse,
    TokenRatesRequest,
    UserResponse,
)
from .services import model_discovery
from .services.auth_service import ServiceError
from .services.wallet_service import display_money


class DiscoveryRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=512)
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class ChannelRequest(DiscoveryRequest):
    discovery_token: str
    provider_model: str = Field(min_length=1, max_length=128)
    priority: int = Field(default=1, ge=1, le=10000)
    rates: TokenRatesRequest


def install_admin_web(app, get_context, get_db):
    assets = Path(__file__).with_name("admin_assets")
    context_dependency = Depends(get_context)
    database_dependency = Depends(get_db)

    def admin(context=context_dependency):
        app.state.auth_service.require_admin(context)
        if context.user.must_change_password:
            raise ServiceError("password_change_required", "请先修改临时密码。", 403)
        return context

    @app.get("/admin", include_in_schema=False)
    def index():
        return asset("index.html")

    def asset(name):
        return FileResponse(assets / name, headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })

    @app.get("/admin/app.js", include_in_schema=False)
    def javascript():
        return asset("app.js")

    @app.get("/admin/style.css", include_in_schema=False)
    def stylesheet():
        return asset("style.css")

    admin_dependency = Depends(admin)

    @app.post("/api/v1/admin/channels/discover")
    def discover(payload: DiscoveryRequest, response: Response, context=admin_dependency):
        base, provider = model_discovery.normalize_url(payload.base_url)
        key = payload.api_key.get_secret_value()
        models = model_discovery.fetch_models(base, key)
        ticket = jwt.encode({
            "aud": "channel-discovery", "sub": context.user.user_id,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "fingerprint": model_discovery.fingerprint(base, key), "models": models,
        }, app.state.settings.jwt_secret, algorithm="HS256")
        response.headers["Cache-Control"] = "no-store"
        return {"models": models, "base_url": base, "provider_type": provider, "discovery_token": ticket}

    @app.post("/api/v1/admin/channels", status_code=201)
    def create_channel(payload: ChannelRequest, context=admin_dependency, db=database_dependency):
        base, provider = model_discovery.normalize_url(payload.base_url)
        key = payload.api_key.get_secret_value()
        try:
            ticket = jwt.decode(payload.discovery_token, app.state.settings.jwt_secret,
                                algorithms=["HS256"], audience="channel-discovery")
            if (ticket["sub"] != context.user.user_id
                    or ticket["fingerprint"] != model_discovery.fingerprint(base, key)
                    or payload.provider_model not in ticket["models"]):
                raise ValueError()
        except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
            raise ServiceError("discovery_required", "连接信息已变更、测试已过期或模型不在清单中，请重新测试连接。", 422) from None
        # Deterministic catalog identity: no manual model precreation or orphan commits.
        code = "auto-" + hashlib.sha256(payload.provider_model.encode()).hexdigest()[:59]
        model = db.scalar(select(ModelDefinition).where(ModelDefinition.code == code))
        if model is None:
            model = ModelDefinition(code=code, display_name=payload.provider_model,
                                    tier="standard", model_multiplier=Decimal(1),
                                    max_output_tokens=8192, enabled=True)
            db.add(model)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise ServiceError("model_exists", "模型正在被其他请求保存，请刷新后重试。", 409) from None
        route = app.state.model_admin_service.create_route(
            db, model_id=model.model_id, provider_type=provider,
            provider_model=payload.provider_model, base_url=base, api_key=key,
            priority=payload.priority, timeout_seconds=90,
            rates=payload.rates.model_dump(),
        )
        return {"route_id": route.route_id, "model_id": model.model_id}

    @app.patch("/api/v1/admin/channels/{route_id}/rates")
    def update_channel_rates(
        route_id: str,
        payload: TokenRatesRequest,
        _context=admin_dependency,
        db=database_dependency,
    ):
        route = app.state.model_admin_service.update_route_rates(
            db,
            route_id=route_id,
            rates=payload.model_dump(),
        )
        return {
            "route_id": route.route_id,
            "rates": {
                "input": str(route.input_rate),
                "output": str(route.output_rate),
                "cache_hit": str(route.cache_hit_rate),
                "cache_miss": str(route.cache_miss_rate),
                "reasoning": str(route.reasoning_rate),
            },
        }

    @app.get("/api/v1/admin/overview")
    def overview(response: Response, _context=admin_dependency, db=database_dependency):
        response.headers["Cache-Control"] = "no-store"
        users = []
        for user in db.scalars(select(User).order_by(User.created_at)):
            item = UserResponse.model_validate(user).model_dump()
            wallet = db.get(Wallet, user.user_id)
            item["balance"] = display_money(wallet.balance) if wallet else "0.00"
            item["billing_multiplier"] = str(user.billing_multiplier)
            users.append(item)
        return {
            "users": users,
            "models": [ModelAdminResponse.model_validate(m).model_dump(mode="json")
                       for m in db.scalars(select(ModelDefinition))],
            "routes": [{
                **ProviderRouteResponse(
                    route_id=r.route_id, model_id=r.model_id, provider_type=r.provider_type,
                    provider_model=r.provider_model, base_url=r.base_url,
                    priority=r.priority, enabled=r.enabled,
                ).model_dump(),
                "rates": {
                    "input": str(r.input_rate),
                    "output": str(r.output_rate),
                    "cache_hit": str(r.cache_hit_rate),
                    "cache_miss": str(r.cache_miss_rate),
                    "reasoning": str(r.reasoning_rate),
                },
            } for r in db.scalars(select(ProviderRoute))],
        }
