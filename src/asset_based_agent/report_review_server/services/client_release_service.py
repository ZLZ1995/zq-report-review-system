"""Admin-controlled, signed client release registry."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..models import ClientRelease, ClientReleaseAudit
DOMAIN = b'ZQ-CLIENT-RELEASE-v1\x00'
PUBLIC_KEYS = {'zq-release-20260917': base64.b64decode('GwMV2oe4mWUq9MQDsfkeGLRMGWFoMhTiAngTSUrsqlU=')}


def canonical_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
from .auth_service import ServiceError

_STATUSES = frozenset({"draft", "canary", "stable", "withdrawn"})
_REQUIRED_PAYLOAD = frozenset({
    "schema_version", "key_id", "sequence", "version", "platform", "arch", "url", "size",
    "sha256", "protocol_min", "protocol_max", "data_schema_min", "data_schema_max",
    "minimum_updater", "issued_at", "expires_at", "notes",
})


def _manifest(raw: Mapping[str, object]) -> tuple[str, dict[str, object], str]:
    if set(raw) != {"payload", "signature"} or not isinstance(raw.get("payload"), dict):
        raise ServiceError("invalid_release_manifest", "发布清单格式无效。", 422)
    payload = raw["payload"]
    assert isinstance(payload, dict)
    signature_text = raw.get("signature")
    key_id = payload.get("key_id")
    if set(payload) != _REQUIRED_PAYLOAD or not isinstance(signature_text, str) or not signature_text or not isinstance(key_id, str) or key_id not in PUBLIC_KEYS:
        raise ServiceError("invalid_release_manifest", "发布清单字段或签名无效。", 422)
    try:
        signature = base64.b64decode(signature_text, validate=True)
        Ed25519PublicKey.from_public_bytes(PUBLIC_KEYS[key_id]).verify(signature, DOMAIN + canonical_payload(payload))
    except (InvalidSignature, ValueError, TypeError, binascii.Error) as exc:
        raise ServiceError("invalid_release_manifest", "发布清单签名校验失败。", 422) from exc
    version = payload.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ServiceError("invalid_release_manifest", "发布版本号无效。", 422)
    platform, arch = payload.get("platform"), payload.get("arch")
    if not all(isinstance(value, str) and value for value in (platform, arch)):
        raise ServiceError("invalid_release_manifest", "发布平台信息无效。", 422)
    sequence = payload.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise ServiceError("invalid_release_manifest", "发布序号无效。", 422)
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return encoded, payload, hashlib.sha256(encoded.encode("ascii")).hexdigest()


class ClientReleaseService:
    def list(self, db: Session) -> list[ClientRelease]:
        return list(db.scalars(select(ClientRelease).order_by(ClientRelease.sequence.desc())))

    def create(self, db: Session, *, admin_user_id: str, manifest: Mapping[str, object]) -> ClientRelease:
        encoded, payload, digest = _manifest(manifest)
        sequence = int(payload["sequence"])
        if db.scalar(select(ClientRelease).where(ClientRelease.sequence == sequence)) is not None:
            raise ServiceError("release_exists", "发布序号已存在。", 409)
        release = ClientRelease(release_id=str(uuid.uuid4()), version=str(payload["version"]),
                                platform=str(payload["platform"]), arch=str(payload["arch"]), sequence=sequence,
                                manifest_json=encoded, manifest_sha256=digest, created_by=admin_user_id, status="draft")
        db.add(release)
        db.add(ClientReleaseAudit(release_id=release.release_id, admin_user_id=admin_user_id, action="create", to_status="draft"))
        db.commit()
        db.refresh(release)
        return release

    def transition(self, db: Session, *, admin_user_id: str, release_id: str, status: str) -> ClientRelease:
        if status not in _STATUSES - {"draft"}:
            raise ServiceError("invalid_release_status", "发布状态不可用。", 422)
        release = db.get(ClientRelease, release_id)
        if release is None:
            raise ServiceError("release_not_found", "发布版本不存在。", 404)
        old = release.status
        if old == "withdrawn" or old == status:
            raise ServiceError("invalid_release_transition", "发布状态不可回退或重复设置。", 409)
        if status == "stable":
            current = db.scalar(select(ClientRelease).where(ClientRelease.status == "stable", ClientRelease.release_id != release_id))
            if current is not None:
                current.status = "withdrawn"
                db.add(ClientReleaseAudit(release_id=current.release_id, admin_user_id=admin_user_id, action="auto_withdraw", from_status="stable", to_status="withdrawn"))
        release.status = status
        db.add(ClientReleaseAudit(release_id=release.release_id, admin_user_id=admin_user_id, action="transition", from_status=old, to_status=status))
        db.commit()
        db.refresh(release)
        return release

    def current(self, db: Session, *, channel: str = "stable") -> dict[str, object]:
        if channel not in {"stable", "canary"}:
            raise ServiceError("invalid_release_channel", "发布通道无效。", 422)
        release = db.scalar(select(ClientRelease).where(ClientRelease.status == channel).order_by(ClientRelease.sequence.desc()))
        if release is None:
            raise ServiceError("release_unavailable", "当前没有可用更新。", 404)
        return {"status": release.status, "version": release.version, "sequence": release.sequence,
                "platform": release.platform, "arch": release.arch, "manifest_sha256": release.manifest_sha256,
                "manifest": json.loads(release.manifest_json)}
