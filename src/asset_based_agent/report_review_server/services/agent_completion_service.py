"""S06：流式 agent completion——Hold/settlement/release、request ID 幂等、
断线对账与加密回放。

复用 MeteredModelService 的计费原语（reserve/capture_hold/_load_billable_
configuration/_record_attempt），不绕开计费与安全体系。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select, update
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

# 二次整改项2：streaming 租约——证明服务端 worker 仍活的唯一凭据
STREAM_LEASE_TTL = timedelta(minutes=5)
_STREAM_RENEW_MIN_INTERVAL_SECONDS = 1.0
UNCERTAIN_PROVIDER_CODES = {
    'provider_usage_invalid', 'provider_usage_missing',
    'provider_network_error', 'provider_invalid_json',
    'provider_invalid_chunk', 'provider_stream_incomplete',
    'provider_finish_missing',
}
MAX_REPLAY_PAYLOAD_BYTES = 8 * 1024 * 1024
# sampling 只允许携带采样参数，不得覆盖线格式保留键
_RESERVED_WIRE_KEYS = frozenset({'messages', 'tools'})


class ReplayPayloadTooLargeError(RuntimeError):
    """canonical replay payload 超过存储上限（S3-02：绝不静默截断）。"""


class CanonicalReplayBuilder:
    """S3-02：把流事件折叠为 canonical replay payload。

    存储语义完整且保序：sequence 逐项记录内容事件，usage /
    message_complete 存原始 data；重放时重新编码为与首次完全一致的
    SSE 事件序列，不再保存/截断原始 delta 数组。
    """

    def __init__(self) -> None:
        self.started = False
        self.sequence: list[dict[str, object]] = []
        self.usage: dict[str, object] | None = None
        self.complete_data: dict[str, object] = {}
        self.message_complete = False
        self._text_parts: list[str] = []
        self._tool_completes: list[dict[str, object]] = []

    def add(self, event: dict[str, object]) -> None:
        kind = event.get('kind')
        data = event.get('data')
        data = data if isinstance(data, dict) else {}
        if kind == 'message_start':
            self.started = True
        elif kind == 'text_delta':
            text = str(data.get('text', ''))
            self._text_parts.append(text)
            self.sequence.append({'kind': 'text_delta', 'text': text})
        elif kind == 'tool_call_delta':
            self.sequence.append({
                'kind': 'tool_call_delta',
                'index': int(data.get('index', 0) or 0),
                'name': str(data.get('name', '')),
                'fragment': str(data.get('arguments_fragment', '')),
            })
        elif kind == 'tool_call_complete':
            entry = {
                'id': str(data.get('id') or ''),
                'name': str(data.get('name', '')),
                'arguments': data.get('arguments'),
            }
            self._tool_completes.append(entry)
            self.sequence.append({'kind': 'tool_call_complete', **entry})
        elif kind == 'usage':
            self.usage = dict(data)
        elif kind == 'message_complete':
            self.message_complete = True
            self.complete_data = dict(data)
        elif kind == 'error':
            pass  # 失败事件不进入成功回放
        else:
            self.sequence.append(
                {'kind': 'raw', 'event': {'kind': kind, 'data': data}})

    def payload(self) -> dict[str, object]:
        return {
            'version': 1,
            'assistant_text': ''.join(self._text_parts),
            'tool_calls': list(self._tool_completes),
            'usage': self.usage,
            'finish_reason': self.complete_data.get('finish_reason'),
            'message_complete': self.message_complete,
            'started': self.started,
            'complete_data': dict(self.complete_data),
            'sequence': list(self.sequence),
        }


def encode_canonical_replay(
        payload: dict[str, object]) -> list[dict[str, object]]:
    """把 canonical replay payload 重新编码为 SSE 事件序列。"""
    events: list[dict[str, object]] = []
    if payload.get('started', True):
        events.append({'kind': 'message_start', 'data': {}})
    sequence = payload.get('sequence') or []
    for item in sequence:  # type: ignore[union-attr]
        kind = item.get('kind')
        if kind == 'text_delta':
            events.append({'kind': 'text_delta',
                           'data': {'text': item.get('text', '')}})
        elif kind == 'tool_call_delta':
            events.append({'kind': 'tool_call_delta', 'data': {
                'index': item.get('index', 0),
                'name': item.get('name', ''),
                'arguments_fragment': item.get('fragment', ''),
            }})
        elif kind == 'tool_call_complete':
            events.append({'kind': 'tool_call_complete', 'data': {
                'id': item.get('id'),
                'name': item.get('name', ''),
                'arguments': item.get('arguments'),
            }})
        elif kind == 'raw':
            events.append(dict(item.get('event') or {}))
    if payload.get('usage') is not None:
        events.append({'kind': 'usage', 'data': dict(payload['usage'])})
    if payload.get('message_complete'):
        events.append({'kind': 'message_complete', 'data': dict(
            payload.get('complete_data')
            or {'finish_reason': payload.get('finish_reason')})})
    return events


def _usage_from_event(event: dict[str, object]) -> NormalizedUsage:
    """流事件中的 usage 严格校验：类型非法一律 provider_usage_invalid。"""
    data = event.get('data')
    if not isinstance(data, dict):
        raise ProviderCallError(
            'provider_usage_invalid', '模型渠道未返回可信Token用量。',
            retryable=False)
    values: dict[str, int] = {}
    for key in ('input_tokens', 'output_tokens', 'cache_hit_tokens',
                'cache_miss_tokens', 'reasoning_tokens'):
        value = data.get(key, 0)
        if type(value) is not int or value < 0:
            raise ProviderCallError(
                'provider_usage_invalid', '模型渠道未返回可信Token用量。',
                retryable=False)
        values[key] = value
    return NormalizedUsage(**values)


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


MAX_TOOL_SCHEMA_BYTES = 16 * 1024
MAX_TOOL_SCHEMA_DEPTH = 16
MAX_TOOL_SCHEMA_PROPERTIES = 128
MAX_TOOL_SCHEMA_TOTAL_PROPERTIES = 512
# 工具 schema 只允许安全的 JSON Schema 子集；$ref/$defs/definitions 等
# 引用类关键字会引入递归爆炸，明确拒绝。
_ALLOWED_SCHEMA_KEYS = frozenset({
    'type', 'properties', 'required', 'items', 'enum', 'const',
    'description', 'title', 'default', 'minimum', 'maximum',
    'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength',
    'pattern', 'format', 'additionalProperties', 'anyOf', 'oneOf',
    'allOf', 'not', 'nullable', 'minItems', 'maxItems', 'uniqueItems',
    'examples', 'minProperties', 'maxProperties',
})


def validate_tool_schemas(tools: list[dict[str, object]]) -> None:
    for tool in tools:
        schema = tool.get('input_schema')
        if not isinstance(schema, dict):
            raise ServiceError(
                'invalid_tool_schema', '工具 input_schema 必须是对象。', 400)
        size = len(json.dumps(schema, ensure_ascii=False).encode('utf-8'))
        if size > MAX_TOOL_SCHEMA_BYTES:
            raise ServiceError(
                'invalid_tool_schema',
                f'工具 input_schema 超过大小限制（{MAX_TOOL_SCHEMA_BYTES} 字节）。',
                400)
        _check_schema_node(schema, depth=1,
                           budget=[MAX_TOOL_SCHEMA_TOTAL_PROPERTIES])


def _check_schema_node(node: object, *, depth: int, budget: list[int]) -> None:
    if not isinstance(node, dict):
        raise ServiceError(
            'invalid_tool_schema', '工具 input_schema 子节点必须是对象。', 400)
    if depth > MAX_TOOL_SCHEMA_DEPTH:
        raise ServiceError(
            'invalid_tool_schema', '工具 input_schema 嵌套深度超限。', 400)
    unknown = sorted(set(node) - _ALLOWED_SCHEMA_KEYS)
    if unknown:
        raise ServiceError(
            'invalid_tool_schema',
            f'工具 input_schema 包含不支持的关键字: {", ".join(unknown)}。', 400)
    properties = node.get('properties')
    if properties is not None and not isinstance(properties, dict):
        raise ServiceError(
            'invalid_tool_schema', '工具 input_schema.properties 必须是对象。',
            400)
    if properties:
        if len(properties) > MAX_TOOL_SCHEMA_PROPERTIES:
            raise ServiceError(
                'invalid_tool_schema',
                '工具 input_schema.properties 数量超限。', 400)
        budget[0] -= len(properties)
        if budget[0] < 0:
            raise ServiceError(
                'invalid_tool_schema',
                '工具 input_schema properties 总数超限。', 400)
    required = node.get('required')
    if required is not None:
        if (not isinstance(required, list)
                or any(type(item) is not str for item in required)):
            raise ServiceError(
                'invalid_tool_schema',
                '工具 input_schema.required 必须是字符串数组。', 400)
        declared = set(properties or ())
        dangling = [name for name in required if name not in declared]
        if dangling:
            raise ServiceError(
                'invalid_tool_schema',
                '工具 input_schema.required 必须对应已声明的 property: '
                + ', '.join(dangling), 400)
    if properties:
        for sub in properties.values():
            _check_schema_node(sub, depth=depth + 1, budget=budget)
    items = node.get('items')
    if isinstance(items, dict):
        _check_schema_node(items, depth=depth + 1, budget=budget)
    elif isinstance(items, list):
        for sub in items:
            _check_schema_node(sub, depth=depth + 1, budget=budget)
    elif items is not None:
        raise ServiceError(
            'invalid_tool_schema', '工具 input_schema.items 必须是对象或数组。',
            400)
    for key in ('anyOf', 'oneOf', 'allOf'):
        branches = node.get(key)
        if branches is None:
            continue
        if not isinstance(branches, list):
            raise ServiceError(
                'invalid_tool_schema',
                f'工具 input_schema.{key} 必须是数组。', 400)
        for sub in branches:
            _check_schema_node(sub, depth=depth + 1, budget=budget)
    additional = node.get('additionalProperties')
    if isinstance(additional, dict):
        _check_schema_node(additional, depth=depth + 1, budget=budget)
    elif additional is not None and not isinstance(additional, bool):
        raise ServiceError(
            'invalid_tool_schema',
            '工具 input_schema.additionalProperties 必须是布尔或对象。', 400)
    negation = node.get('not')
    if negation is not None:
        _check_schema_node(negation, depth=depth + 1, budget=budget)


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
            status='streaming', started_at=utc_now(),
            last_activity_at=utc_now(),
            lease_expires_at=utc_now() + STREAM_LEASE_TTL)
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
        stored = json.loads(self.cipher.decrypt(
            existing.response_ciphertext,
            purpose=f'billing-response:{existing.billing_request_id}'))
        if isinstance(stored, list):
            events = stored  # 旧格式：原始事件数组（S3-02 之前的存量行）
        else:
            events = encode_canonical_replay(stored)
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

        二次整改项2：stale streaming（lease 过期）在此惰性清扫为 uncertain，
        绝不向客户端返回永久 busy；live streaming 只读上报 lease_live。
        """
        billing = db.scalar(
            select(BillingRequest).where(
                BillingRequest.user_id == user_id,
                BillingRequest.client_request_id == client_request_id,
            ))
        if billing is None:
            return None
        if (billing.status == 'streaming'
                and (billing.lease_expires_at is None
                     or is_expired(billing.lease_expires_at))):
            sweep_stale_streaming(db)
            db.refresh(billing)
        lease_live = bool(
            billing.status == 'streaming'
            and billing.lease_expires_at is not None
            and not is_expired(billing.lease_expires_at))
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
            'lease_live': lease_live,
        }

    # --------------------------------------------------------------- 流式

    def stream(
        self,
        db: Session,
        prepared: PreparedStream,
    ) -> Iterator[dict[str, object]]:
        """产出 SSE 事件 dict；任何分支都留下可对账状态。

        S3-01 terminal guard：按执行阶段（provider_started / usage 可信 /
        settled）分类异常——
        - provider 未开始：failed + release hold
        - provider 已开始、usage 不可信：uncertain
        - 已拿到可信 usage：按已知 usage 结算后 failed
        - GeneratorExit：disconnected
        任何出口后 billing.status != 'streaming'。
        """
        billing, hold, route = prepared.billing, prepared.hold, prepared.route
        user, model = prepared.user, prepared.model
        wire_payload = prepared.wire_payload
        replay = CanonicalReplayBuilder()
        usage: NormalizedUsage | None = None
        provider_started = False

        def track(event):
            replay.add(event)
            return event

        last_renew = time.monotonic()
        try:
            for event in self.metered.provider_client.stream(
                    route, wire_payload):
                provider_started = True
                if event.get('kind') == 'usage':
                    usage = _usage_from_event(event)
                last_renew = self._renew_stream_lease(db, billing, last_renew)
                yield track(event)
            if usage is None:
                raise ProviderCallError(
                    'provider_usage_missing', '模型渠道未返回可信Token用量。',
                    retryable=False)
            charge = _charge_for_usage(route, usage, model, user)
            self.metered._record_attempt(
                db, billing, route, 1, 'succeeded', usage, model, user, None,
                commit=False)
            self._settle_success(db, billing=billing, hold=hold,
                                 charge=charge, replay=replay)
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
        except Exception:  # noqa: BLE001 - terminal guard：内部异常也必须落终态
            yield track({'kind': 'error', 'data': self._internal_failure(
                db, billing=billing, hold=hold, route=route, user=user,
                model=model, provider_started=provider_started,
                usage=usage)})

    def _renew_stream_lease(self, db: Session, billing,
                            last_renew: float) -> float:
        """二次整改项2：每个 chunk/usage/receipt 事件刷新活性与租约（限频）。

        条件 UPDATE 只在仍为 streaming 时生效；终态已被其他路径写掉时静默
        跳过。返回最近一次续租的 monotonic 时间。
        """
        now_mono = time.monotonic()
        if now_mono - last_renew < _STREAM_RENEW_MIN_INTERVAL_SECONDS:
            return last_renew
        db.execute(
            update(BillingRequest)
            .where(
                BillingRequest.billing_request_id == billing.billing_request_id,
                BillingRequest.status == 'streaming',
            )
            .values(
                last_activity_at=utc_now(),
                lease_expires_at=utc_now() + STREAM_LEASE_TTL,
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return now_mono

    def _settle_success(self, db: Session, *, billing, hold, charge,
                        replay: CanonicalReplayBuilder):
        payload_json = json.dumps(
            replay.payload(), ensure_ascii=False, separators=(',', ':'))
        if len(payload_json.encode('utf-8')) > MAX_REPLAY_PAYLOAD_BYTES:
            raise ReplayPayloadTooLargeError(
                'canonical replay payload 超过存储上限')
        self.metered.wallet_service.charge(
            db, user_id=billing.user_id, amount=money(charge),
            reference_id=billing.billing_request_id)
        hold.status = 'captured'
        hold.settled_amount = money(charge)
        billing.status = 'succeeded'
        billing.charged_amount = money(charge)
        billing.response_ciphertext = self.cipher.encrypt(
            payload_json,
            purpose=f'billing-response:{billing.billing_request_id}')
        billing.response_expires_at = utc_now() + timedelta(hours=24)
        billing.completed_at = utc_now()
        db.commit()

    def _internal_failure(self, db: Session, *, billing, hold, route, user,
                          model, provider_started: bool,
                          usage: NormalizedUsage | None):
        """S3-01：非 provider 协议异常（DB/加密/扣费/未知内部错误）的终态兜底。

        结算自身再失败时，通过独立会话落 uncertain，保证任何出口后
        billing.status != 'streaming'。
        """
        code = 'internal_error'
        try:
            db.rollback()
            if not provider_started:
                self.metered._record_attempt(
                    db, billing, route, 1, 'failed', NormalizedUsage(),
                    model, user, code, commit=False)
                hold.status = 'released'
                billing.status = 'failed'
                billing.error_code = code
                billing.charged_amount = money(0)
                billing.completed_at = utc_now()
                db.commit()
                return {'code': code, 'message': '服务内部错误，未产生费用。'}
            if usage is None:
                billing.status = 'uncertain'
                billing.error_code = code
                hold.status = 'uncertain'
                self.metered._record_attempt(
                    db, billing, route, 1, 'uncertain', NormalizedUsage(),
                    model, user, code, commit=False)
                db.commit()
                return {'code': 'billing_reconciliation_required',
                        'message': '渠道结果不可核验，需要对账。'}
            charge = _charge_for_usage(route, usage, model, user)
            self.metered._record_attempt(
                db, billing, route, 1, 'failed', usage, model, user, code,
                commit=False)
            if charge:
                self.metered.wallet_service.charge(
                    db, user_id=billing.user_id, amount=money(charge),
                    reference_id=billing.billing_request_id)
            hold.status = 'captured' if charge else 'released'
            hold.settled_amount = money(charge)
            billing.status = 'failed'
            billing.charged_amount = money(charge)
            billing.error_code = code
            billing.completed_at = utc_now()
            db.commit()
            return {'code': code,
                    'message': '服务内部错误，已按已核验用量结算。'}
        except Exception:  # noqa: BLE001 - 结算再失败：独立会话落可对账状态
            db.rollback()
            self._mark_uncertain(billing.billing_request_id)
            return {'code': 'billing_reconciliation_required',
                    'message': '渠道结果不可核验，需要对账。'}

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

    def _mark_uncertain(self, billing_request_id: str) -> None:
        """S3-01：结算不可恢复时，独立会话落 uncertain（请求会话可能已坏）。

        兜底会话自身也失败时不再上抛——已无任何可持久化手段，避免在错误
        处理路径上二次崩穿。
        """
        try:
            with self.session_factory() as db:
                billing = db.get(BillingRequest, billing_request_id)
                if billing is None or billing.status != 'streaming':
                    return
                hold = db.get(BalanceHold, billing.hold_id)
                billing.status = 'uncertain'
                billing.error_code = 'internal_error'
                billing.completed_at = utc_now()
                if hold is not None and hold.status == 'active':
                    hold.status = 'uncertain'
                db.commit()
        except Exception:  # noqa: BLE001 - 兜底路径不再上抛
            return


def sweep_stale_streaming(db: Session) -> int:
    """二次整改项2：清扫 lease 过期的 streaming 请求为 uncertain。

    服务进程在写入 streaming 后崩溃会留下永久 busy 的中间态；lease 过期即
    证明无活 worker，必须进入可恢复（对账）状态。关联 active hold 一并标记
    uncertain，等待人工/自动对账，绝不私自释放或扣费。幂等，返回清扫数量。
    """
    stale = list(db.scalars(select(BillingRequest).where(
        BillingRequest.status == 'streaming',
        (BillingRequest.lease_expires_at.is_(None))
        | (BillingRequest.lease_expires_at < utc_now()),
    )))
    for billing in stale:
        billing.status = 'uncertain'
        billing.error_code = 'stream_lease_expired'
        billing.completed_at = utc_now()
        hold = db.get(BalanceHold, billing.hold_id)
        if hold is not None and hold.status == 'active':
            hold.status = 'uncertain'
    if stale:
        db.commit()
    return len(stale)


def replay_events(replay: ReplayResult) -> Iterator[dict[str, object]]:
    yield from replay.events
    yield {'kind': 'receipt', 'data': {
        'billing_request_id': replay.billing_request_id,
        'charged_amount': str(replay.charged_amount),
        'replayed': True}}
