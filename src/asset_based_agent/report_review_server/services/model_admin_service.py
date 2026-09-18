"""Model, route, pricing, and user multiplier administration."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..crypto import SecretCipher
from ..models import ModelDefinition, ProviderRoute, User
from .auth_service import ServiceError
from .wallet_service import money


class ModelAdminService:
    def __init__(self, cipher: SecretCipher) -> None:
        self.cipher = cipher

    def create_model(
        self,
        db: Session,
        *,
        code: str,
        display_name: str,
        tier: str,
        model_multiplier: Decimal,
        max_output_tokens: int,
    ) -> ModelDefinition:
        multiplier = Decimal(model_multiplier).quantize(Decimal("0.000001"))
        if multiplier <= 0:
            raise ServiceError("invalid_multiplier", "模型倍率必须大于零。", 422)
        model = ModelDefinition(
            code=code.strip(),
            display_name=display_name.strip(),
            tier=tier.strip(),
            model_multiplier=multiplier,
            max_output_tokens=max_output_tokens,
            enabled=True,
        )
        db.add(model)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ServiceError("model_exists", "模型代码已存在。", 409) from exc
        db.refresh(model)
        return model

    def create_route(
        self,
        db: Session,
        *,
        model_id: str,
        provider_type: str,
        provider_model: str,
        base_url: str,
        api_key: str,
        priority: int,
        timeout_seconds: int,
        rates: dict[str, Decimal],
    ) -> ProviderRoute:
        if db.get(ModelDefinition, model_id) is None:
            raise ServiceError("model_not_found", "模型不存在。", 404)
        normalized_rates = {name: money(value) for name, value in rates.items()}
        if any(value < 0 for value in normalized_rates.values()):
            raise ServiceError("invalid_rate", "Token价格不能为负数。", 422)
        route = ProviderRoute(
            model_id=model_id,
            provider_type=provider_type,
            provider_model=provider_model.strip(),
            base_url=base_url.rstrip("/"),
            api_key_ciphertext=self.cipher.encrypt(
                api_key,
                purpose=f"provider-route:{model_id}:{priority}",
            ),
            priority=priority,
            timeout_seconds=timeout_seconds,
            enabled=True,
            input_rate=normalized_rates["input"],
            output_rate=normalized_rates["output"],
            cache_hit_rate=normalized_rates["cache_hit"],
            cache_miss_rate=normalized_rates["cache_miss"],
            reasoning_rate=normalized_rates["reasoning"],
        )
        db.add(route)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ServiceError("route_priority_exists", "渠道优先级已存在。", 409) from exc
        db.refresh(route)
        return route

    @staticmethod
    def update_route_rates(
        db: Session,
        *,
        route_id: str,
        rates: dict[str, Decimal],
    ) -> ProviderRoute:
        route = db.get(ProviderRoute, route_id)
        if route is None:
            raise ServiceError("route_not_found", "渠道不存在。", 404)
        normalized = {name: money(value) for name, value in rates.items()}
        if any(value < 0 for value in normalized.values()):
            raise ServiceError("invalid_rate", "Token价格不能为负数。", 422)
        route.input_rate = normalized["input"]
        route.output_rate = normalized["output"]
        route.cache_hit_rate = normalized["cache_hit"]
        route.cache_miss_rate = normalized["cache_miss"]
        route.reasoning_rate = normalized["reasoning"]
        db.commit()
        db.refresh(route)
        return route

    @staticmethod
    def list_public_models(db: Session) -> list[ModelDefinition]:
        return list(
            db.scalars(
                select(ModelDefinition)
                .where(ModelDefinition.enabled.is_(True))
                .order_by(ModelDefinition.tier, ModelDefinition.display_name)
            )
        )

    @staticmethod
    def set_user_multiplier(
        db: Session,
        *,
        user_id: str,
        multiplier: Decimal,
    ) -> None:
        normalized = Decimal(multiplier).quantize(Decimal("0.000001"))
        if normalized <= 0:
            raise ServiceError("invalid_multiplier", "用户倍率必须大于零。", 422)
        user = db.scalar(select(User).where(User.user_id == user_id).with_for_update())
        if user is None:
            raise ServiceError("user_not_found", "用户不存在。", 404)
        user.billing_multiplier = normalized
        db.commit()
