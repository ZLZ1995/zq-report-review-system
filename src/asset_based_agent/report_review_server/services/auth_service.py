"""Remote account and single-session authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..config import ServerSettings
from ..models import AuthSession, User, Wallet, utc_now
from ..schemas import TokenResponse, UserResponse
from ..security import (
    decode_access_token,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    verify_password,
)


class ServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


class AuthService:
    def __init__(self, settings: ServerSettings) -> None:
        self.settings = settings

    def login(
        self,
        db: Session,
        *,
        username: str,
        password: str,
        client_instance_id: str,
    ) -> TokenResponse:
        normalized = normalize_username(username)
        user = db.scalar(select(User).where(User.username == normalized).with_for_update())
        if (
            user is None
            or user.status != "active"
            or not verify_password(password, user.password_hash)
        ):
            raise ServiceError("invalid_credentials", "用户名或密码错误。", 401)
        self._revoke_user_sessions(db, user.user_id, "replaced_by_new_login")
        return self._new_session(db, user, client_instance_id)

    def refresh(self, db: Session, refresh_token: str) -> TokenResponse:
        token_hash = hash_refresh_token(refresh_token)
        auth_session = db.scalar(
            select(AuthSession)
            .where(AuthSession.refresh_token_hash == token_hash)
            .with_for_update()
        )
        if (
            auth_session is None
            or auth_session.revoked_at is not None
            or is_expired(auth_session.expires_at)
        ):
            raise ServiceError("invalid_refresh_token", "刷新令牌无效或已过期。", 401)
        user = db.get(User, auth_session.user_id)
        if user is None or user.status != "active":
            raise ServiceError("account_disabled", "账号不可用。", 401)
        rotated = new_refresh_token()
        auth_session.refresh_token_hash = hash_refresh_token(rotated)
        auth_session.last_heartbeat_at = utc_now()
        db.commit()
        return self._token_response(user, auth_session, rotated)

    def authenticate_access(self, db: Session, token: str) -> AuthContext:
        try:
            payload = decode_access_token(self.settings, token)
        except jwt.PyJWTError as exc:
            raise ServiceError("invalid_access_token", "访问令牌无效或已过期。", 401) from exc
        if payload.get("type") != "access":
            raise ServiceError("invalid_access_token", "访问令牌类型错误。", 401)
        session_id = str(payload.get("sid") or "")
        user_id = str(payload.get("sub") or "")
        auth_session = db.get(AuthSession, session_id)
        if (
            auth_session is None
            or auth_session.user_id != user_id
            or auth_session.revoked_at is not None
        ):
            raise ServiceError("session_revoked", "当前会话已失效。", 401)
        if is_expired(auth_session.expires_at):
            raise ServiceError("session_expired", "当前会话已过期。", 401)
        user = db.get(User, user_id)
        if user is None or user.status != "active":
            raise ServiceError("account_disabled", "账号不可用。", 401)
        return AuthContext(user=user, session=auth_session)

    def heartbeat(self, db: Session, context: AuthContext) -> None:
        context.session.last_heartbeat_at = utc_now()
        db.commit()

    def logout(self, db: Session, context: AuthContext) -> None:
        context.session.revoked_at = utc_now()
        context.session.revoked_reason = "logout"
        db.commit()

    def change_password(
        self,
        db: Session,
        context: AuthContext,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        user = db.scalar(select(User).where(User.user_id == context.user.user_id).with_for_update())
        if user is None or not verify_password(current_password, user.password_hash):
            raise ServiceError("invalid_current_password", "当前密码错误。", 400)
        user.password_hash = _account_password_hash(new_password, customer=user.role == "user")
        user.must_change_password = False
        self._revoke_user_sessions(db, user.user_id, "password_changed")
        db.commit()

    def create_user(
        self,
        db: Session,
        *,
        username: str,
        display_name: str,
        temporary_password: str,
        email: str | None = None,
    ) -> User:
        normalized = normalize_username(username)
        user = User(
            username=normalized,
            display_name=display_name.strip(),
            email=email.strip().lower() if email else None,
            password_hash=_account_password_hash(temporary_password, customer=True),
            role="user",
            status="active",
            must_change_password=True,
            registration_source="admin",
        )
        db.add(user)
        try:
            db.flush()
            db.add(Wallet(user_id=user.user_id))
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ServiceError("username_exists", "用户名或邮箱已存在。", 409) from exc
        db.refresh(user)
        return user

    def reset_password(
        self,
        db: Session,
        *,
        user_id: str,
        temporary_password: str,
    ) -> None:
        user = db.scalar(select(User).where(User.user_id == user_id).with_for_update())
        if user is None:
            raise ServiceError("user_not_found", "用户不存在。", 404)
        user.password_hash = _account_password_hash(temporary_password, customer=user.role == "user")
        user.must_change_password = True
        self._revoke_user_sessions(db, user.user_id, "password_reset")
        db.commit()

    def require_admin(self, context: AuthContext) -> None:
        if context.user.role != "admin":
            raise ServiceError("admin_required", "需要管理员权限。", 403)

    def _new_session(
        self,
        db: Session,
        user: User,
        client_instance_id: str,
    ) -> TokenResponse:
        refresh_token = new_refresh_token()
        auth_session = AuthSession(
            user_id=user.user_id,
            client_instance_id=client_instance_id.strip(),
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=utc_now() + timedelta(days=self.settings.refresh_token_days),
        )
        db.add(auth_session)
        db.commit()
        db.refresh(auth_session)
        return self._token_response(user, auth_session, refresh_token)

    def _token_response(
        self,
        user: User,
        auth_session: AuthSession,
        refresh_token: str,
    ) -> TokenResponse:
        access_token, expires_in = issue_access_token(
            self.settings,
            user_id=user.user_id,
            session_id=auth_session.session_id,
            role=user.role,
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )

    @staticmethod
    def _revoke_user_sessions(db: Session, user_id: str, reason: str) -> None:
        db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now(), revoked_reason=reason)
        )


def bootstrap_admin(
    session_factory: sessionmaker[Session],
    *,
    username: str,
    password: str,
    display_name: str = "Administrator",
) -> User:
    with session_factory() as db:
        normalized = normalize_username(username)
        existing = db.scalar(select(User).where(User.username == normalized))
        if existing is not None:
            if existing.role != "admin":
                raise ValueError("bootstrap username already belongs to a non-admin user")
            return existing
        user = User(
            username=normalized,
            display_name=display_name.strip() or normalized,
            password_hash=hash_password(password),
            role="admin",
            status="active",
            must_change_password=False,
            registration_source="bootstrap",
        )
        db.add(user)
        db.flush()
        db.add(Wallet(user_id=user.user_id))
        db.commit()
        db.refresh(user)
        return user


def normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not normalized or any(character.isspace() for character in normalized):
        raise ServiceError("invalid_username", "用户名格式无效。", 422)
    return normalized


def _account_password_hash(password: str, *, customer: bool) -> str:
    try:
        return hash_password(password, customer=customer)
    except ValueError:
        message = ("客户密码须为8–16位纯数字或数字与英文字母组合，区分大小写。"
                   if customer else "管理员密码须为12–256位。")
        raise ServiceError("invalid_password", message, 422) from None


def is_expired(value: datetime, *, now: datetime | None = None) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return value <= reference
