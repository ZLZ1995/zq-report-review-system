"""Account-scoped, immutable data-only packages; installation is not execution permission."""

import json
from pathlib import Path

from .skill_package import MAX_PACKAGE_BYTES, inspect_package_bytes
from .store import now


class SkillInstallation:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS installed_skills (
                    owner TEXT NOT NULL, skill_id TEXT NOT NULL, version TEXT NOT NULL,
                    name TEXT NOT NULL, sha256 TEXT NOT NULL, package BLOB NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
                    PRIMARY KEY(owner,skill_id,version));
                CREATE UNIQUE INDEX IF NOT EXISTS one_enabled_skill_version
                    ON installed_skills(owner,skill_id) WHERE enabled=1;
                CREATE TABLE IF NOT EXISTS skill_install_events (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, skill_id TEXT NOT NULL,
                    version TEXT, action TEXT NOT NULL, created TEXT NOT NULL);
            """)

    def install(self, path: Path, *, confirmed: bool, expected_sha256: str | None = None):
        if not confirmed:
            raise ValueError("安装 Skill 必须明确确认")
        with path.open("rb") as stream:
            raw = stream.read(MAX_PACKAGE_BYTES + 1)
        package = inspect_package_bytes(raw)
        if expected_sha256 is not None and package.sha256 != expected_sha256:
            raise ValueError("确认后 Skill 包已变化，请重新选择并确认")
        manifest = package.manifest
        identity, version = manifest["id"], manifest["version"]
        if identity in {"report.review", "review.preflight"}:
            raise ValueError("不能覆盖内置 Skill ID")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT sha256 FROM installed_skills WHERE owner=? AND skill_id=? AND version=?",
                (self.store.owner, identity, version),
            ).fetchone()
            if previous:
                if previous[0] != package.sha256:
                    raise ValueError("同版本内容不同，请使用新版本号")
                return package
            db.execute("INSERT INTO installed_skills VALUES(?,?,?,?,?,?,0,?)",
                       (self.store.owner, identity, version, manifest["name"], package.sha256, raw, now()))
            self._event(db, identity, version, "install")
        return package

    def list_versions(self):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT skill_id,version,name,sha256,enabled,created FROM installed_skills "
                "WHERE owner=? ORDER BY skill_id,created,version", (self.store.owner,)
            )]

    def _load(self, db, identity, version):
        row = db.execute(
            "SELECT package,sha256 FROM installed_skills WHERE owner=? AND skill_id=? AND version=?",
            (self.store.owner, identity, version),
        ).fetchone()
        if row is None:
            raise PermissionError("Skill 版本不存在或无权访问")
        package = inspect_package_bytes(row[0])
        if (package.sha256 != row[1] or package.manifest["id"] != identity
                or package.manifest["version"] != version):
            raise ValueError("已安装 Skill 完整性校验失败")
        return package

    def load(self, identity, version):
        with self.store.connect() as db:
            return self._load(db, identity, version)

    def _require_idle(self, db, identity):
        rows = db.execute(
            "SELECT r.snapshot FROM runs r JOIN sessions s ON s.id=r.session "
            "JOIN projects p ON p.id=s.project WHERE p.owner=? "
            "AND r.state IN ('queued','running','validating','interrupted')", (self.store.owner,)
        )
        for row in rows:
            try:
                snapshot = json.loads(row[0])
            except (ValueError, TypeError) as exc:
                raise ValueError("未结束任务记录异常，需先核对") from exc
            if not isinstance(snapshot, dict) or snapshot.get("skill_id") == identity:
                raise ValueError("Skill 存在未结束任务，请先核对任务状态")

    def activate(self, identity, version, *, confirmed: bool):
        if not confirmed:
            raise ValueError("启用 Skill 必须明确确认")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_idle(db, identity)
            package = self._load(db, identity, version)
            if not package.ready:
                raise ValueError("Skill 依赖不满足：" + ", ".join(package.missing_dependencies))
            db.execute("UPDATE installed_skills SET enabled=0 WHERE owner=? AND skill_id=?",
                       (self.store.owner, identity))
            db.execute("UPDATE installed_skills SET enabled=1 WHERE owner=? AND skill_id=? AND version=?",
                       (self.store.owner, identity, version))
            self._event(db, identity, version, "activate")

    def disable(self, identity, *, confirmed: bool):
        if not confirmed:
            raise ValueError("停用 Skill 必须明确确认")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_idle(db, identity)
            rows = db.execute("SELECT version FROM installed_skills WHERE owner=? AND skill_id=?",
                              (self.store.owner, identity)).fetchall()
            if not rows:
                raise PermissionError("Skill 不存在或无权访问")
            db.execute("UPDATE installed_skills SET enabled=0 WHERE owner=? AND skill_id=?",
                       (self.store.owner, identity))
            self._event(db, identity, None, "disable")

    def _event(self, db, identity, version, action):
        db.execute("INSERT INTO skill_install_events(owner,skill_id,version,action,created) VALUES(?,?,?,?,?)",
                   (self.store.owner, identity, version, action, now()))
