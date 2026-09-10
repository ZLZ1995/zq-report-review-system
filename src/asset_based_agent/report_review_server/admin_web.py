"""Independent control desk assets and explicitly scoped administrative reads."""

from pathlib import Path

from fastapi import Depends, Response
from fastapi.responses import FileResponse
from sqlalchemy import select

from .models import ModelDefinition, ProviderRoute, User, Wallet
from .schemas import ModelAdminResponse, ProviderRouteResponse, UserResponse
from .services.auth_service import ServiceError
from .services.wallet_service import display_money


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
            "routes": [ProviderRouteResponse(
                route_id=r.route_id, model_id=r.model_id, provider_type=r.provider_type,
                provider_model=r.provider_model, base_url=r.base_url,
                priority=r.priority, enabled=r.enabled,
            ).model_dump() for r in db.scalars(select(ProviderRoute))],
        }
