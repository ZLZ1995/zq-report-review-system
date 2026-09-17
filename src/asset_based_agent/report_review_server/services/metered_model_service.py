"""Idempotent provider routing with reservation and atomic settlement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import ServerSettings
from ..crypto import SecretCipher
from ..models import (
    BalanceHold,
    BillingRequest,
    ModelDefinition,
    ProviderAttempt,
    ProviderRoute,
    User,
    utc_now,
)
from .auth_service import ServiceError, is_expired
from .provider_gateway import (
    NormalizedUsage,
    ProviderCallError,
    ProviderClient,
)
from .wallet_service import MONEY_QUANTUM, WalletService, money


class InsufficientBalanceError(ServiceError):
    def __init__(self) -> None:
        super().__init__("insufficient_balance", "余额不足，无法开始本轮审核。", 402)


class MeteredExecutionError(ServiceError):
    def __init__(self, code: str = "all_providers_failed") -> None:
        super().__init__(code, "所有模型渠道均调用失败。", 502)


class BillingReconciliationRequired(ServiceError):
    def __init__(self) -> None:
        super().__init__("billing_reconciliation_required",
                         "模型请求费用待核对，已暂停新的付费调用，请联系管理员；不要重复提交。", 409)


@dataclass(frozen=True)
class MeteredResult:
    payload: dict[str, object]
    charged_amount: Decimal
    billing_request_id: str


class MeteredModelService:
    def __init__(
        self,
        settings: ServerSettings,
        provider_client: ProviderClient,
    ) -> None:
        self.settings = settings
        self.provider_client = provider_client
        self.wallet_service = WalletService()
        self.cipher = SecretCipher(settings.encryption_key_bytes())

    def execute(
        self,
        db: Session,
        *,
        user_id: str,
        model_id: str,
        client_request_id: str,
        estimated_usage: NormalizedUsage,
        payload: dict[str, object],
        external_hold_id: str | None = None,
        defer_settlement: bool = False,
    ) -> MeteredResult:
        request_hash = _request_hash(model_id, payload)
        existing = db.scalar(
            select(BillingRequest).where(
                BillingRequest.user_id == user_id,
                BillingRequest.client_request_id == client_request_id,
            )
        )
        if existing is not None:
            return self._existing_result(existing, request_hash)

        user, model, routes = self._load_billable_configuration(
            db, user_id=user_id, model_id=model_id
        )
        if external_hold_id is None:
            hold = self.reserve(
                db,
                user_id=user_id,
                model_id=model_id,
                client_request_id=client_request_id,
                estimated_usages=[estimated_usage],
                commit=False,
            )
        else:
            hold = self._load_external_hold(
                db,
                hold_id=external_hold_id,
                user_id=user_id,
                model_id=model_id,
            )
        billing_request = BillingRequest(
            user_id=user_id,
            model_id=model_id,
            hold_id=hold.hold_id,
            client_request_id=client_request_id,
            request_hash=request_hash,
        )
        db.add(billing_request)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raced = db.scalar(
                select(BillingRequest).where(
                    BillingRequest.user_id == user_id,
                    BillingRequest.client_request_id == client_request_id,
                )
            )
            if raced is None:
                raise
            return self._existing_result(raced, request_hash)

        total_charge = Decimal("0.00000000")
        last_error_code = "all_providers_failed"
        for attempt_number, route in enumerate(routes, start=1):
            try:
                response = self.provider_client.call(route, payload)
            except ProviderCallError as exc:
                if exc.usage is None and exc.code in {
                    "provider_usage_invalid", "provider_usage_missing",
                    "provider_network_error", "provider_invalid_json",
                }:
                    billing_request.status = "uncertain"
                    billing_request.error_code = exc.code
                    hold.status = "uncertain"
                    hold.settled_amount = money(hold.settled_amount + total_charge)
                    self._record_attempt(
                        db, billing_request, route, attempt_number, "uncertain",
                        NormalizedUsage(), model, user, exc.code,
                    )
                    raise BillingReconciliationRequired() from exc
                usage = exc.usage or NormalizedUsage()
                attempt_charge = _charge_for_usage(route, usage, model, user)
                total_charge = money(total_charge + attempt_charge)
                self._record_attempt(
                    db,
                    billing_request,
                    route,
                    attempt_number,
                    "failed",
                    usage,
                    model,
                    user,
                    exc.code,
                )
                last_error_code = exc.code
                if not exc.retryable:
                    break
                continue

            attempt_charge = _charge_for_usage(route, response.usage, model, user)
            total_charge = money(total_charge + attempt_charge)
            self._record_attempt(
                db,
                billing_request,
                route,
                attempt_number,
                "succeeded",
                response.usage,
                model,
                user,
                None,
            )
            return self._complete_success(
                db,
                billing_request=billing_request,
                hold=hold,
                response_payload=response.payload,
                total_charge=total_charge,
                defer_settlement=defer_settlement,
            )

        self._complete_failure(
            db,
            billing_request=billing_request,
            hold=hold,
            total_charge=total_charge,
            error_code=last_error_code,
            defer_settlement=defer_settlement,
        )
        raise MeteredExecutionError(last_error_code)

    def reserve(
        self,
        db: Session,
        *,
        user_id: str,
        model_id: str,
        client_request_id: str,
        estimated_usages: list[NormalizedUsage],
        commit: bool = True,
        hold_minutes: int = 30,
    ) -> BalanceHold:
        self._require_reconciled(db, user_id)
        existing = db.scalar(
            select(BalanceHold).where(
                BalanceHold.user_id == user_id,
                BalanceHold.client_request_id == client_request_id,
            )
        )
        if existing is not None:
            if existing.model_id != model_id:
                raise ServiceError(
                    "idempotency_conflict",
                    "相同请求编号对应了不同模型。",
                    409,
                )
            return existing
        user, model, routes = self._load_billable_configuration(
            db, user_id=user_id, model_id=model_id
        )
        reserved_amount = money(
            sum(
                (
                    _charge_for_usage(route, usage, model, user)
                    for usage in estimated_usages
                    for route in routes
                ),
                Decimal(0),
            )
        )
        wallet = self.wallet_service.get_wallet(db, user_id, lock=True)
        self._require_reconciled(db, user_id)
        active_holds = db.scalar(
            select(func.coalesce(func.sum(BalanceHold.reserved_amount), 0)).where(
                BalanceHold.user_id == user_id,
                BalanceHold.status == "active",
                BalanceHold.expires_at > utc_now(),
            )
        )
        available = money(wallet.balance - Decimal(active_holds or 0))
        if available < reserved_amount:
            db.rollback()
            raise InsufficientBalanceError()
        hold = BalanceHold(
            user_id=user_id,
            model_id=model_id,
            client_request_id=client_request_id,
            reserved_amount=reserved_amount,
            expires_at=utc_now() + timedelta(minutes=hold_minutes),
        )
        db.add(hold)
        if commit:
            db.commit()
            db.refresh(hold)
        else:
            db.flush()
        return hold

    def capture_hold(self, db: Session, *, hold_id: str, reference_id: str) -> BalanceHold:
        hold = db.scalar(
            select(BalanceHold).where(BalanceHold.hold_id == hold_id).with_for_update()
        )
        if hold is None:
            raise ServiceError("hold_not_found", "费用冻结记录不存在。", 404)
        if hold.status == "uncertain":
            raise BillingReconciliationRequired()
        if hold.status == "captured":
            return hold
        if hold.status != "active":
            raise ServiceError("hold_not_active", "费用冻结记录已失效。", 409)
        self.wallet_service.charge(
            db,
            user_id=hold.user_id,
            amount=money(hold.settled_amount),
            reference_id=reference_id,
        )
        hold.status = "captured" if hold.settled_amount else "released"
        db.commit()
        db.refresh(hold)
        return hold

    def _load_external_hold(
        self,
        db: Session,
        *,
        hold_id: str,
        user_id: str,
        model_id: str,
    ) -> BalanceHold:
        hold = db.scalar(
            select(BalanceHold).where(BalanceHold.hold_id == hold_id).with_for_update()
        )
        if hold is None or hold.user_id != user_id or hold.model_id != model_id:
            raise ServiceError("hold_not_found", "费用冻结记录不存在。", 404)
        self._require_reconciled(db, user_id)
        if hold.status != "active" or is_expired(hold.expires_at):
            raise ServiceError("hold_not_active", "费用冻结记录已失效。", 409)
        return hold

    def _require_reconciled(self, db: Session, user_id: str) -> None:
        uncertain = db.scalar(select(BalanceHold.hold_id).where(
            BalanceHold.user_id == user_id, BalanceHold.status == "uncertain",
        ).limit(1))
        if uncertain is not None:
            raise BillingReconciliationRequired()

    def _load_billable_configuration(
        self,
        db: Session,
        *,
        user_id: str,
        model_id: str,
    ) -> tuple[User, ModelDefinition, list[ProviderRoute]]:
        user = db.get(User, user_id)
        if user is None or user.status != "active":
            raise ServiceError("account_disabled", "账号不可用。", 401)
        model = db.get(ModelDefinition, model_id)
        if model is None or not model.enabled:
            raise ServiceError("model_unavailable", "模型当前不可用。", 409)
        routes = list(
            db.scalars(
                select(ProviderRoute)
                .where(
                    ProviderRoute.model_id == model_id,
                    ProviderRoute.enabled.is_(True),
                )
                .order_by(ProviderRoute.priority)
            )
        )
        if not routes:
            raise ServiceError("provider_unavailable", "模型没有可用渠道。", 503)
        return user, model, routes

    def _record_attempt(
        self,
        db: Session,
        billing_request: BillingRequest,
        route: ProviderRoute,
        attempt_number: int,
        status: str,
        usage: NormalizedUsage,
        model: ModelDefinition,
        user: User,
        error_code: str | None,
    ) -> None:
        base_cost = _base_cost(route, usage)
        charged_amount = _charge_for_usage(route, usage, model, user)
        db.add(
            ProviderAttempt(
                billing_request_id=billing_request.billing_request_id,
                route_id=route.route_id,
                attempt_number=attempt_number,
                status=status,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_hit_tokens=usage.cache_hit_tokens,
                cache_miss_tokens=usage.cache_miss_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                base_cost=base_cost,
                charged_amount=charged_amount,
                error_code=error_code,
            )
        )
        db.commit()

    def _complete_success(
        self,
        db: Session,
        *,
        billing_request: BillingRequest,
        hold: BalanceHold,
        response_payload: dict[str, object],
        total_charge: Decimal,
        defer_settlement: bool,
    ) -> MeteredResult:
        if defer_settlement:
            hold.settled_amount = money(hold.settled_amount + total_charge)
        else:
            self.wallet_service.charge(
                db,
                user_id=billing_request.user_id,
                amount=total_charge,
                reference_id=billing_request.billing_request_id,
            )
            hold.status = "captured"
            hold.settled_amount = total_charge
        billing_request.status = "succeeded"
        billing_request.charged_amount = total_charge
        billing_request.response_ciphertext = self.cipher.encrypt(
            json.dumps(response_payload, ensure_ascii=False, separators=(",", ":")),
            purpose=f"billing-response:{billing_request.billing_request_id}",
        )
        billing_request.response_expires_at = utc_now() + timedelta(hours=24)
        billing_request.completed_at = utc_now()
        db.commit()
        return MeteredResult(
            payload=response_payload,
            charged_amount=total_charge,
            billing_request_id=billing_request.billing_request_id,
        )

    def _complete_failure(
        self,
        db: Session,
        *,
        billing_request: BillingRequest,
        hold: BalanceHold,
        total_charge: Decimal,
        error_code: str,
        defer_settlement: bool,
    ) -> None:
        if defer_settlement:
            hold.settled_amount = money(hold.settled_amount + total_charge)
        else:
            self.wallet_service.charge(
                db,
                user_id=billing_request.user_id,
                amount=total_charge,
                reference_id=billing_request.billing_request_id,
            )
            hold.status = "captured" if total_charge else "released"
            hold.settled_amount = total_charge
        billing_request.status = "failed"
        billing_request.charged_amount = total_charge
        billing_request.error_code = error_code
        billing_request.completed_at = utc_now()
        db.commit()

    def _existing_result(
        self,
        request: BillingRequest,
        request_hash: str,
    ) -> MeteredResult:
        if request.request_hash != request_hash:
            raise ServiceError(
                "idempotency_conflict",
                "相同请求编号对应了不同内容。",
                409,
            )
        if request.status == "pending":
            raise ServiceError("request_in_progress", "请求仍在处理中。", 409)
        if request.status == "uncertain":
            raise BillingReconciliationRequired()
        if request.status == "failed":
            raise MeteredExecutionError(request.error_code or "all_providers_failed")
        if (
            not request.response_ciphertext
            or not request.response_expires_at
            or is_expired(request.response_expires_at)
        ):
            raise ServiceError(
                "idempotent_result_expired",
                "该请求已结算，但临时结果已经过期。",
                410,
            )
        payload = json.loads(
            self.cipher.decrypt(
                request.response_ciphertext,
                purpose=f"billing-response:{request.billing_request_id}",
            )
        )
        return MeteredResult(
            payload=payload,
            charged_amount=money(request.charged_amount),
            billing_request_id=request.billing_request_id,
        )


def _base_cost(route: ProviderRoute, usage: NormalizedUsage) -> Decimal:
    weighted = (
        Decimal(usage.input_tokens) * route.input_rate
        + Decimal(usage.output_tokens) * route.output_rate
        + Decimal(usage.cache_hit_tokens) * route.cache_hit_rate
        + Decimal(usage.cache_miss_tokens) * route.cache_miss_rate
        + Decimal(usage.reasoning_tokens) * route.reasoning_rate
    )
    return (weighted / Decimal(1000000)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _charge_for_usage(
    route: ProviderRoute,
    usage: NormalizedUsage,
    model: ModelDefinition,
    user: User,
) -> Decimal:
    return (_base_cost(route, usage) * model.model_multiplier * user.billing_multiplier).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )


def _request_hash(model_id: str, payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {"model_id": model_id, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
