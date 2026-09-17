"""Remote authentication, protected refresh-token storage, and connectivity state."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx


class RemoteAuthenticationError(ValueError):
    pass


class CredentialStorageError(RemoteAuthenticationError):
    pass


class NetworkUnavailable(RemoteAuthenticationError):
    pass


class ServerCapabilityUnavailable(RemoteAuthenticationError):
    pass


class SessionRevoked(RemoteAuthenticationError):
    pass


class InsufficientBalance(RemoteAuthenticationError):
    pass


BILLING_RECONCILIATION_MESSAGE = (
    "模型请求费用待核对，新的付费调用已暂停。请联系管理员核对原请求，不要重复提交。"
)


class BillingReconciliationRequired(RemoteAuthenticationError):
    pass


class CredentialStore(Protocol):
    def get(self, account: str) -> str | None: ...

    def set(self, account: str, value: str) -> None: ...

    def delete(self, account: str) -> None: ...


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, account: str) -> str | None:
        return self.values.get(account)

    def set(self, account: str, value: str) -> None:
        self.values[account] = value

    def delete(self, account: str) -> None:
        self.values.pop(account, None)


class WindowsCredentialStore:
    """Store refresh tokens as Windows generic credentials."""

    def __init__(self, service_name: str = "ZQReportReview") -> None:
        self.service_name = service_name

    def get(self, account: str) -> str | None:
        import pywintypes
        import win32cred

        try:
            credential = win32cred.CredRead(
                self._target(account),
                win32cred.CRED_TYPE_GENERIC,
            )
        except pywintypes.error as exc:
            if getattr(exc, "winerror", None) == 1168:
                return None
            raise
        value = credential.get("CredentialBlob")
        if isinstance(value, bytes):
            return value.decode("utf-16-le")
        return str(value) if value else None

    def set(self, account: str, value: str) -> None:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": self._target(account),
                "UserName": account,
                "CredentialBlob": value,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )

    def delete(self, account: str) -> None:
        import pywintypes
        import win32cred

        try:
            win32cred.CredDelete(
                self._target(account),
                win32cred.CRED_TYPE_GENERIC,
            )
        except pywintypes.error as exc:
            if getattr(exc, "winerror", None) != 1168:
                raise

    def _target(self, account: str) -> str:
        return f"{self.service_name}:refresh:{account}"


class RemoteSessionClient:
    def __init__(
        self,
        base_url: str,
        *,
        client_instance_id: str,
        credential_store: CredentialStore,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = _validated_base_url(base_url)
        self.client_instance_id = client_instance_id
        self.credential_store = credential_store
        self.http_client = http_client or httpx.Client(timeout=15.0)
        self.access_token: str | None = None
        self.user: dict[str, object] | None = None

    def login(self, username: str, password: str) -> dict[str, str]:
        payload = self._post(
            "/auth/login",
            {
                "username": username,
                "password": password,
                "client_instance_id": self.client_instance_id,
            },
        )
        self._accept_token_payload(payload)
        return self.user_summary()

    def refresh(self) -> None:
        refresh_token = self.credential_store.get(self.client_instance_id)
        if not refresh_token:
            raise SessionRevoked("登录凭据已失效，请重新登录。")
        payload = self._post("/auth/refresh", {"refresh_token": refresh_token})
        self._accept_token_payload(payload)

    def heartbeat(self) -> None:
        response = self._authenticated_post("/auth/heartbeat")
        if response.status_code == 401:
            code, _message = _error_detail(response)
            if code == "session_revoked":
                raise SessionRevoked("当前账号已在其他客户端登录。")
            self.refresh()
            response = self._authenticated_post("/auth/heartbeat")
        self._raise_for_response(response)

    def logout(self) -> None:
        try:
            if self.access_token:
                response = self._authenticated_post("/auth/logout")
                if response.status_code not in {204, 401}:
                    self._raise_for_response(response)
        finally:
            self.access_token = None
            self.user = None
            self.credential_store.delete(self.client_instance_id)

    def list_models(self) -> list[dict[str, object]]:
        payload = self._authenticated_json("GET", "/models")
        if not isinstance(payload, list):
            raise RemoteAuthenticationError("服务端模型列表格式无效。")
        return [item for item in payload if isinstance(item, dict)]

    def get_balance(self) -> dict[str, str]:
        payload = self._authenticated_json("GET", "/account/balance")
        if not isinstance(payload, dict):
            raise RemoteAuthenticationError("服务端余额格式无效。")
        balance = payload.get("balance")
        currency = payload.get("currency")
        if not isinstance(balance, str) or not isinstance(currency, str):
            raise RemoteAuthenticationError("服务端余额格式无效。")
        return {"balance": balance, "currency": currency}

    def create_review_job(self, payload: dict[str, object]) -> dict[str, object]:
        self.require_capability('review_jobs', '/review-jobs')
        result = self._authenticated_json("POST", "/review-jobs", payload)
        if not isinstance(result, dict):
            raise RemoteAuthenticationError("服务端审核任务格式无效。")
        return result

    def route_skill(self, payload: dict[str, object], *, cancel=None) -> dict[str, object]:
        from .task_cancellation import TaskCancelled
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        self.require_capability('skill_routing', '/skill-route')
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        result = self._model_json('/skill-route', payload, cancel=cancel)
        if not isinstance(result, dict):
            raise RemoteAuthenticationError('任务路由响应格式无效')
        return result

    def route_skill_cancellable(self, payload: dict[str, object], cancel) -> dict[str, object]:
        return self.route_skill(payload, cancel=cancel)

    def understand_task(self, payload: dict[str, object], *, cancel=None) -> dict[str, object]:
        from ...agent_contracts import (
            TaskUnderstanding,
            UnderstandingRequest,
            validate_understanding,
        )
        from .task_cancellation import TaskCancelled
        request = UnderstandingRequest.model_validate(payload)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        self.require_capability('task_understanding', '/agent/understand')
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        if any(skill.id == 'browser.task' for skill in request.skills):
            try:
                self.require_capability('browser_step', '/agent/browser-step')
            except ServerCapabilityUnavailable:
                # Older servers must not receive an unsupported adapter enum.
                # Keep all existing file capabilities; validate the reply against
                # exactly the reduced catalog sent to this server.
                request = request.model_copy(update={
                    'skills': [skill for skill in request.skills if skill.id != 'browser.task']})
            if cancel is not None and cancel.is_set():
                raise TaskCancelled()
        result = self._model_json('/agent/understand', request.model_dump(), cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        try:
            return validate_understanding(request, TaskUnderstanding.model_validate(result)).model_dump()
        except (TypeError, ValueError) as exc:
            raise RemoteAuthenticationError('任务理解结果无效，未开始业务执行。') from exc

    def propose_browser_step(self, payload: dict[str, object], *, cancel=None) -> dict[str, object]:
        from ...browser_contracts import (
            BrowserStepProposal,
            BrowserStepRequest,
            validate_browser_step,
        )
        from .task_cancellation import TaskCancelled
        request = BrowserStepRequest.model_validate(payload)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        self.require_capability('browser_step', '/agent/browser-step')
        if set(request.scope.actions) & {'scroll', 'wait'}:
            self.require_capability('browser_view_actions', '/agent/browser-step', allow_legacy=False)
        if 'login' in request.scope.actions:
            self.require_capability('browser_saved_login', '/agent/browser-step', allow_legacy=False)
        if 'download' in request.scope.actions:
            self.require_capability('browser_download', '/agent/browser-step', allow_legacy=False)
        if request.generated_downloads:
            try:
                self.require_capability('browser_generated_download', '/agent/browser-step', allow_legacy=False)
            except ServerCapabilityUnavailable:
                # Preserve the old link-only protocol; validate the reply against
                # this reduced request so an old server cannot suggest a button.
                request = request.model_copy(update={'generated_downloads': False})
        if 'upload' in request.scope.actions:
            self.require_capability('browser_upload', '/agent/browser-step', allow_legacy=False)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        result = self._model_json('/agent/browser-step', request.model_dump(), cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        try:
            return validate_browser_step(request, BrowserStepProposal.model_validate(result)).model_dump()
        except (TypeError, ValueError) as exc:
            raise RemoteAuthenticationError('浏览器动作建议无效，未执行网页操作。') from exc

    def propose_plan(self, payload: dict[str, object], *, cancel=None) -> dict[str, object]:
        from ...agent_contracts import PlanningRequest, PlanProposal, validate_proposal
        from .task_cancellation import TaskCancelled
        request = PlanningRequest.model_validate(payload)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        self.require_capability('task_planning', '/agent/plan')
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        result = self._model_json('/agent/plan', request.model_dump(), cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        try:
            return validate_proposal(request, PlanProposal.model_validate(result)).model_dump()
        except (TypeError, ValueError) as exc:
            raise RemoteAuthenticationError('任务计划无效，未开始业务执行。') from exc

    def require_capability(self, capability: str, endpoint: str, *, allow_legacy: bool = True) -> None:
        """Read-only preflight; legacy support is verified, never guessed."""
        if not self.access_token:
            raise SessionRevoked('当前没有有效登录会话。')
        try:
            response = self.http_client.get(self.base_url + '/capabilities')
            if response.status_code == 404:
                if not allow_legacy:
                    raise ServerCapabilityUnavailable('服务端未声明此浏览器能力，请先升级服务端。')
                parsed = urlparse(self.base_url)
                response = self.http_client.get(f'{parsed.scheme}://{parsed.netloc}/openapi.json')
                response.raise_for_status()
                data = response.json()
                operation = data.get('paths', {}).get(parsed.path + endpoint, {}).get('post')
                supported = isinstance(operation, dict)
            else:
                response.raise_for_status()
                data = response.json()
                capabilities = data.get('capabilities', {})
                supported = (type(data.get('schema_version')) is int and data['schema_version'] == 1 and
                             type(data.get('protocol_version')) is int and data['protocol_version'] == 1 and
                             isinstance(capabilities, dict) and
                             type(capabilities.get(capability)) is int and capabilities[capability] == 1)
        except httpx.RequestError as exc:
            raise NetworkUnavailable('无法连接服务端进行能力预检，未发起任务。') from exc
        except (ValueError, AttributeError, TypeError, httpx.HTTPStatusError) as exc:
            raise ServerCapabilityUnavailable('服务端能力信息不可用，未发起任务。') from exc
        if not supported:
            raise ServerCapabilityUnavailable('服务端缺少兼容的任务接口，请联系管理员升级；未发起任务。')

    def analyze_materials(self, payload: dict[str, object], *, cancel=None) -> dict[str, object]:
        self.require_capability('material_analysis', '/material-analysis')
        result = self._model_json('/material-analysis', payload, cancel=cancel)
        if not isinstance(result, dict):
            raise RemoteAuthenticationError('资料识别返回格式无效。')
        return result

    def analyze_materials_cancellable(self, payload, cancel):
        return self.analyze_materials(payload, cancel=cancel)

    def cancel_review_job(self, job_id: str):
        return self._authenticated_json('POST', f'/review-jobs/{job_id}/cancel')

    def execute_review_job(self, job_id: str, *, cancel=None) -> dict[str, object]:
        result = self._model_json(f"/review-jobs/{job_id}/execute", cancel=cancel)
        if not isinstance(result, dict):
            raise RemoteAuthenticationError("服务端审核结果格式无效。")
        return result

    def execute_review_job_cancellable(self, job_id, cancel):
        return self.execute_review_job(job_id, cancel=cancel)

    def _model_json(self, path, payload=None, *, cancel=None):
        from .resource_locks import CLIENT_RESOURCES
        # This runs inside the actual HTTP worker: cancelling its caller must
        # not release a slot while the submitted request is still in flight.
        with CLIENT_RESOURCES.lease(('model',), cancel):
            return self._authenticated_json('POST', path, payload)

    def get_review_job(self, job_id: str) -> dict[str, object]:
        result = self._authenticated_json("GET", f"/review-jobs/{job_id}")
        if not isinstance(result, dict):
            raise RemoteAuthenticationError("服务端审核进度格式无效。")
        return result

    def user_summary(self) -> dict[str, str]:
        if self.user is None:
            raise SessionRevoked("当前没有有效登录会话。")
        username = str(self.user.get("username") or "")
        return {
            "username": username,
            "display_name": str(self.user.get("display_name") or username),
        }

    def _authenticated_post(self, path: str) -> httpx.Response:
        if not self.access_token:
            raise SessionRevoked("当前没有有效登录会话。")
        try:
            return self.http_client.post(
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        except httpx.RequestError as exc:
            raise NetworkUnavailable("无法连接审核服务，请检查网络。") from exc

    def _authenticated_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        retry: bool = True,
    ) -> object:
        if not self.access_token:
            raise SessionRevoked("当前没有有效登录会话。")
        try:
            response = self.http_client.request(
                method,
                self.base_url + path,
                json=payload,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        except httpx.RequestError as exc:
            raise NetworkUnavailable("无法连接审核服务，请检查网络。") from exc
        if (response.status_code in (404, 405) and
                path in {'/skill-route', '/material-analysis', '/review-jobs'} and
                _error_detail(response)[0] == 'http_error'):
            raise ServerCapabilityUnavailable('服务端任务接口不可用，请联系管理员核对部署版本和网关配置。')
        if response.status_code == 401 and retry:
            code, _message = _error_detail(response)
            if code == "session_revoked":
                raise SessionRevoked("当前账号已在其他客户端登录。")
            self.refresh()
            return self._authenticated_json(method, path, payload, retry=False)
        self._raise_for_response(response)
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RemoteAuthenticationError("服务端返回格式无效。") from exc

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        try:
            response = self.http_client.post(self.base_url + path, json=payload)
        except httpx.RequestError as exc:
            raise NetworkUnavailable("无法连接审核服务，请检查网络。") from exc
        self._raise_for_response(response)
        try:
            result = response.json()
        except ValueError as exc:
            raise RemoteAuthenticationError("服务端返回格式无效。") from exc
        if not isinstance(result, dict):
            raise RemoteAuthenticationError("服务端返回格式无效。")
        return result

    def _accept_token_payload(self, payload: dict[str, object]) -> None:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        user = payload.get("user")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise RemoteAuthenticationError("服务端登录响应缺少令牌。")
        if not isinstance(user, dict):
            raise RemoteAuthenticationError("服务端登录响应缺少用户信息。")
        try:
            self.credential_store.set(self.client_instance_id, refresh_token)
        except Exception:  # noqa: BLE001 - do not expose OS errors containing credentials
            self.access_token = None
            self.user = None
            raise CredentialStorageError("本机安全凭据保存失败，请检查 Windows 凭据管理器。") from None
        self.access_token = access_token
        self.user = dict(user)

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        code, message = _error_detail(response)
        if code == "billing_reconciliation_required":
            raise BillingReconciliationRequired(BILLING_RECONCILIATION_MESSAGE)
        if code == "session_revoked":
            raise SessionRevoked(message or "当前会话已失效。")
        if code == "insufficient_balance":
            raise InsufficientBalance(message or "余额不足，无法开始本轮审核。")
        if response.status_code == 401:
            raise RemoteAuthenticationError("用户名或密码错误，或登录已失效。")
        raise RemoteAuthenticationError(message or "远程服务请求失败。")


class RemoteAuthService:
    is_remote = True

    def __init__(self, client: RemoteSessionClient) -> None:
        self.client = client

    def authenticate(self, username: str, password: str) -> dict[str, str]:
        return self.client.login(username, password)


class ConnectivitySupervisor:
    def __init__(
        self,
        heartbeat: Callable[[], None],
        *,
        checkpoint: Callable[[], None],
        force_exit: Callable[[], None],
        heartbeat_interval_seconds: int = 10,
        reconnect_grace_seconds: int = 30,
        retry_interval_seconds: int = 1,
    ) -> None:
        self.heartbeat = heartbeat
        self.checkpoint = checkpoint
        self.force_exit = force_exit
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.reconnect_grace_seconds = reconnect_grace_seconds
        self.retry_interval_seconds = retry_interval_seconds
        self.state = "connected"
        self.disconnected_at: float | None = None
        self.next_attempt_at = float(heartbeat_interval_seconds)

    def tick(self, *, now: float | None = None) -> str:
        moment = time.monotonic() if now is None else now
        if self.state == "terminated" or moment < self.next_attempt_at:
            return self.state
        if (
            self.disconnected_at is not None
            and moment - self.disconnected_at >= self.reconnect_grace_seconds
        ):
            return self._terminate()
        try:
            self.heartbeat()
        except SessionRevoked:
            return self._terminate()
        except NetworkUnavailable:
            if self.disconnected_at is None:
                self.disconnected_at = moment
            self.state = "reconnecting"
            self.next_attempt_at = moment + self.retry_interval_seconds
            return self.state
        except RemoteAuthenticationError:
            return self._terminate()
        self.state = "connected"
        self.disconnected_at = None
        self.next_attempt_at = moment + self.heartbeat_interval_seconds
        return self.state

    def _terminate(self) -> str:
        if self.state != "terminated":
            self.state = "terminated"
            try:
                self.checkpoint()
            except Exception:
                pass
            finally:
                self.force_exit()
        return self.state


def load_or_create_client_instance_id(path: Path) -> str:
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        value = payload.get("client_instance_id") if isinstance(payload, dict) else None
        if isinstance(value, str) and len(value) >= 32:
            return value
    client_instance_id = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"client_instance_id": client_instance_id}),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return client_instance_id


def _validated_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("report review server URL must use HTTPS")
    return normalized


def _error_detail(response: httpx.Response) -> tuple[str, str]:
    try:
        payload = response.json()
    except ValueError:
        return "http_error", ""
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return "http_error", ""
    error = payload["error"]
    return str(error.get("code") or "http_error"), str(error.get("message") or "")
