"""Authenticated platform bootstrap; no provider key is accepted by this client."""

from __future__ import annotations

import hashlib
import threading

from ..report_review_app.services.remote_auth_service import RemoteSessionClient


class PlatformSession:
    def __init__(self, client: RemoteSessionClient):
        self.client = client
        self.lock = threading.RLock()

    def login(self, username: str, password: str) -> dict:
        with self.lock:
            self.client.login(username, password)
            if (self.client.user or {}).get("must_change_password"):
                return {"must_change_password": True}
            return self.bootstrap()

    def change_password(self, current: str, new: str) -> dict:
        with self.lock:
            username = str((self.client.user or {}).get("username") or "")
            if not username:
                raise ValueError("请先登录")
            self.client._authenticated_json(
                "POST",
                "/auth/change-password",
                {"current_password": current, "new_password": new},
            )
            # Server revokes every old session after a password change.
            self.client.access_token = None
            self.client.user = None
            self.client.credential_store.delete(self.client.client_instance_id)
            return self.login(username, new)

    def bootstrap(self) -> dict:
        user = self.client.user or {}
        if not user.get("user_id") or user.get("must_change_password"):
            raise ValueError("账号状态不允许进入工作台")
        models = self.client.list_models()
        if not models:
            raise ValueError("管理员尚未配置可用模型")
        for model in models:
            if not isinstance(model.get("model_id"), str) or not model["model_id"]:
                raise ValueError("模型列表格式无效")
        owner = hashlib.sha256(
            f"{self.client.base_url}|{user['user_id']}".encode()
        ).hexdigest()
        return {
            "must_change_password": False,
            "owner": owner,
            "models": models,
            "balance": self.client.get_balance(),
            "display_name": user.get("display_name", user.get("username", "")),
        }


class ConnectionState:
    """Pure state machine driven by UI ticks, even while a probe is pending."""

    def __init__(self):
        self.state = "connected"
        self.lost_at: float | None = None

    def observe(self, outcome: str, now: float) -> str:
        if self.state == "terminated":
            return self.state
        if (
            self.lost_at is not None
            and now - self.lost_at >= 30
            or outcome == "revoked"
        ):
            self.state = "terminated"
        elif outcome == "ok":
            self.state, self.lost_at = "connected", None
        elif outcome == "offline":
            if self.lost_at is None:
                self.lost_at = now
            self.state = "reconnecting"
        return self.state
