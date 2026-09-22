"""S06：流式 agent completion——Hold/settlement/release、request ID 幂等、
断线对账与加密回放。

复用 MeteredModelService 的计费原语（reserve/capture_hold/_load_billable_
configuration/_record_attempt），不绕开计费与安全体系。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..crypto import SecretCipher
from ..models import (
    BalanceHold,
    BillingRequest,
    utc_now,
)
from .auth_service import ServiceError, is_expired
from .metered_model_service import (
    BillingReconciliationRequired,
    MeteredModelService,
    _charge_for_usage,
    _request_hash,
)
from .provider_gateway import NormalizedUsage, ProviderCallError
from .wallet_service import money

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..models import ModelDefinition, ProviderRoute, User

SUPPORTED_PROTOCOL_VERSIONS = (1,)
UNCERTAIN_PROVIDER_CODES = {
    'provider_usage_invalid', 'provider_usage_missing',
    'provider_network_error', 'provider_invalid_json',
}
MAX_STORED_EVENTS = 2000
# sampling 只允许携带采样参数，不得覆盖线格式保留键
_RESERVED_WIRE_KEYS = frozenset({'messages', 'tools'})


@dataclass
class PreparedStream:
    billing: BillingRequest
    hold: BalanceHold
    user: User
    model: ModelDefinition
    route: ProviderRoute
    wire_payload: dict[str, object]


@dataclass
class ReplayResult:
    events: list[dict[str, object]]
    charged_amount: Decimal
    billing_request_id: str


def validate_tool_schemas(tools: list[dict[str, object]]) -> None:
    for tool in tools:
        schema = tool.get('input_schema')
        if not isinstance(schema, dict):
            raise ServiceError(
                'invalid_tool_schema', '工具 input_schema 必须是对象。', 400)
        properties = schema.get('properties')
        if properties is not None and not isinstance(properties, dict):
            raise ServiceError(
                'invalid_tool_schema', '工具 input_schema.properties 必须是对象。',
                400)
        required = schema.get('required')
        if required is not None and (
                not isinstance(required, list)
                or any(type(item) is not str for item in required)):
            raise ServiceError(
                'invalid_tool_schema',
                '工具 input_schema.required 必须是字符串数组。', 400)


def estimate_usage(messages: list[dict[str, object]], *,
                   max_output_tokens: int) -> NormalizedUsage:
    characters = sum(len(str(message.get('content', '')))
                     for message in messages)
    return NormalizedUsage(
        input_tokens=max(1, characters // 4 + 64),
        output_tokens=max(1, min(4096, max_output_tokens)),
    )


class AgentCompletionService:
    def __init__(self, metered: MeteredModelService, session_factory) -> None:
        self.metered = metered
        self.cipher: SecretCipher = metered.cipher
        self.session_factory = session_factory

    # --------------------------------------------------------------- 入口

    def begin(
        self,
        db: Session,
        *,
        user_id: str,
        model_id: str,
        client_request_id: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        sampling: dict[str, object],
    ) -> PreparedStream | ReplayResult:
        validate_tool_schemas(tools)
        wire_payload: dict[str, object] = {
            'messages': [{'role': m['role'], 'content': m['content']}
                         for m in messages],
        }
        if tools:
            wire_payload['tools'] = [
                {'type': 'function', 'function': {
                    'name': tool['name'],
                    'description': tool.get('description', ''),
                    'parameters': tool['input_schema'],
                }} for tool in tools]
        if sampling:
            wire_payload.update({key: value for key, value in sampling.items()
                                 if key not in _RESERVED_WIRE_KEYS})
        request_hash = _request_hash(model_id, wire_payload)
        existing = db.scalar(
            select(BillingRequest).where(
                BillingRequest.user_id == user_id,
                BillingRequest.client_request_id == client_request_id,
            ))
        if existing is not None:
            return self._replay(existing, request_hash)
        user, model, routes = self.metered._load_billable_configuration(
            db, user_id=user_id, model_id=model_id)
        route = routes[0]
        hold = self.metered.reserve(
            db, user_id=user_id, model_id=model_id,
            client_request_id=client_request_id,
            estimated_usages=[
                estimate_usage(messages,
                               max_output_tokens=model.max_output_tokens)],
            commit=False)
        billing = BillingRequest(
            user_id=user_id, model_id=model_id, hold_id=hold.hold_id,
            client_request_id=client_request_id, request_hash=request_hash,
            status='streaming')
        db.add(billing)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raced = db.scalar(
                select(BillingRequest).where(
                    BillingRequest.user_id == user_id,
                    BillingRequest.client_request_id == client_request_id,
                ))
            if raced is None:
                raise
            return self._replay(raced, request_hash)
        return PreparedStream(
            billing=billing, hold=hold, user=user, model=model, route=route,
            wire_payload=wire_payload)

    # --------------------------------------------------------------- 回放

    def _replay(
        self,
        existing: BillingRequest,
        request_hash: str,
    ) -> ReplayResult:
        if existing.request_hash != request_hash:
            raise ServiceError(
                'idempotency_conflict', '相同请求编号对应了不同内容。', 409)
        return self._replay_stored(existing)

    def replay_by_request_id(
        self,
        db: Session,
        *,
        user_id: str,
        client_request_id: str,
    ) -> ReplayResult:
        """S2-03：对账回放——按 client_request_id 取回已存储的事件流。

        与 _replay 的差异：调用方是断线恢复的客户端，手里没有原始 payload，
        因此跳过 request_hash 校验；其余状态门禁完全一致。
        """
        billing = db.scalar(
            select(BillingRequest).where(
                BillingRequest.user_id == user_id,
                BillingRequest.client_request_id == client_request_id,
            ))
        if billing is None:
            raise ServiceError('completion_not_found', '没有该请求的记录。', 404)
        return self._replay_stored(billing)

    def _replay_stored(self, existing: BillingRequest) -> ReplayResult:
        if existing.status == 'streaming':
            raise ServiceError('request_in_progress', '请求仍在处理中。', 409)
        if existing.status in ('uncertain', 'disconnected'):
            raise BillingReconciliationRequired()
        if existing.status == 'failed':
            return ReplayResult(
                events=[{'kind': 'error', 'data': {
                    'code': existing.error_code or 'all_providers_failed',
                    'message': '该请求此前已失败（幂等回放）。'}}],
                charged_amount=money(existing.charged_amount),
                billing_request_id=existing.billing_request_id)
        if (not existing.response_ciphertext
                or not existing.response_expires_at
                or is_expired(existing.response_expires_at)):
            raise ServiceError(
                'idempotent_result_expired',
                '该请求已结算，但临时结果已经过期。', 410)
        events = json.loads(self.cipher.decrypt(
            existing.response_ciphertext,
            purpose=f'billing-response:{existing.billing_request_id}'))
        return ReplayResult(
            events=events,
            charged_amount=money(existing.charged_amount),
            billing_request_id=existing.billing_request_id)

    # --------------------------------------------------------------- 对账

    def reconcile(
        self,
        db: Session,
        *,
        user_id: str,
        client_request_id: str,
    ) -> dict[str, object] | None:
        """S2-03：按 client_request_id 返回可对账状态；无记录返回 None。

        只读查询：不触碰计费、不触发回放、不改任何状态。
        """
        billing = db.scalar(
            select(BillingRequest).where(
                BillingRequest.user_id == user_id,
                BillingRequest.client_request_id == client_request_id,
            ))
        if billing is None:
            return None
        replay_available = bool(
            billing.status == 'succeeded'
            and billing.response_ciphertext
            and billing.response_expires_at is not None
            and not is_expired(billing.response_expires_at))
        return {
            'status': billing.status,
            'billing_request_id': billing.billing_request_id,
            'replay_available': replay_available,
            'error_code': billing.error_code or '',
        }

    # --------------------------------------------------------------- 流式

    def stream(
        self,
        db: Session,
        prepared: PreparedStream,
    ) -> Iterator[dict[str, object]]:
        """产出 SSE 事件 dict；任何分支都留下可对账状态。"""
        billing, hold, route = prepared.billing, prepared.hold, prepared.route
        user, model = prepared.user, prepared.model
        wire_payload = prepared.wire_payload
        emitted: list[dict[str, object]] = []
        usage: NormalizedUsage | None = None

        def track(event):
            if len(emitted) < MAX_STORED_EVENTS:
                emitted.append(event)
            return event

        try:
            for event in self.metered.provider_client.stream(
                    route, wire_payload):
                if event['kind'] == 'usage':
                    data = event['data']
                    usage = NormalizedUsage(
                        input_tokens=int(data.get('input_tokens', 0)),
                        output_tokens=int(data.get('output_tokens', 0)),
                        cache_hit_tokens=int(data.get('cache_hit_tokens', 0)),
                        cache_miss_tokens=int(
                            data.get('cache_miss_tokens', 0)),
                        reasoning_tokens=int(
                            data.get('reasoning_tokens', 0)))
                yield track(event)
            if usage is None:
                raise ProviderCallError(
                    'provider_usage_missing', '模型渠道未返回可信Token用量。',
                    retryable=False)
            charge = _charge_for_usage(route, usage, model, user)
            self.metered._record_attempt(
                db, billing, route, 1, 'succeeded', usage, model, user, None)
            self._settle_success(db, billing=billing, hold=hold,
                                 charge=charge, events=emitted)
            yield {'kind': 'receipt', 'data': {
                'billing_request_id': billing.billing_request_id,
                'charged_amount': str(money(charge)),
                'usage': dict(zip(
                    ('input_tokens', 'output_tokens', 'cache_hit_tokens',
                     'cache_miss_tokens', 'reasoning_tokens'),
                    usage.values(), strict=True)),
                'replayed': False}}
        except ProviderCallError as exc:
            yield track({'kind': 'error', 'data': self._provider_failure(
                db, billing=billing, hold=hold, route=route, user=user,
                model=model, exc=exc)})
        except GeneratorExit:
            self._mark_disconnected(billing.billing_request_id)
            raise

    def _settle_success(self, db: Session, *, billing, hold, charge, events):
        self.metered.wallet_service.charge(
            db, user_id=billing.user_id, amount=money(charge),
            reference_id=billing.billing_request_id)
        hold.status = 'captured'
        hold.settled_amount = money(charge)
        billing.status = 'succeeded'
        billing.charged_amount = money(charge)
        billing.response_ciphertext = self.cipher.encrypt(
            json.dumps(events, ensure_ascii=False, separators=(',', ':')),
            purpose=f'billing-response:{billing.billing_request_id}')
        billing.response_expires_at = utc_now() + timedelta(hours=24)
        billing.completed_at = utc_now()
        db.commit()

    def _provider_failure(self, db: Session, *, billing, hold, route, user,
                          model, exc: ProviderCallError):
        if exc.usage is None and exc.code in UNCERTAIN_PROVIDER_CODES:
            billing.status = 'uncertain'
            billing.error_code = exc.code
            hold.status = 'uncertain'
            self.metered._record_attempt(
                db, billing, route, 1, 'uncertain', NormalizedUsage(),
                model, user, exc.code)
            db.commit()
            return {'code': 'billing_reconciliation_required',
                    'message': '渠道结果不可核验，需要对账。'}
        usage = exc.usage or NormalizedUsage()
        charge = _charge_for_usage(route, usage, model, user)
        self.metered._record_attempt(
            db, billing, route, 1, 'failed', usage, model, user, exc.code)
        if charge:
            self.metered.wallet_service.charge(
                db, user_id=billing.user_id, amount=money(charge),
                reference_id=billing.billing_request_id)
        hold.status = 'captured' if charge else 'released'
        hold.settled_amount = money(charge)
        billing.status = 'failed'
        billing.charged_amount = money(charge)
        billing.error_code = exc.code
        billing.completed_at = utc_now()
        db.commit()
        return {'code': exc.code, 'message': exc.message}

    def _mark_disconnected(self, billing_request_id: str) -> None:
        """客户端断线：独立会话标记可对账状态（请求会话可能已关闭）。"""
        with self.session_factory() as db:
            billing = db.get(BillingRequest, billing_request_id)
            if billing is None or billing.status != 'streaming':
                return
            hold = db.get(BalanceHold, billing.hold_id)
            billing.status = 'disconnected'
            billing.error_code = 'client_disconnected'
            billing.completed_at = utc_now()
            if hold is not None and hold.status == 'active':
                hold.status = 'released'  # 无可信用量，释放冻结
            db.commit()


def replay_events(replay: ReplayResult) -> Iterator[dict[str, object]]:
    yield from replay.events
    yield {'kind': 'receipt', 'data': {
        'billing_request_id': replay.billing_request_id,
        'charged_amount': str(replay.charged_amount),
        'replayed': True}}
