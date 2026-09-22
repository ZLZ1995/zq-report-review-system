"""S03：v13 additive 迁移——备份、幂等、数据保留与回滚。"""
import shutil
import sqlite3

AGENT_TABLES = {
    'agent_sessions', 'agent_lanes', 'conversation_entries', 'agent_operations',
    'agent_turns', 'agent_tool_calls', 'agent_operation_events',
    'turn_file_bindings', 'project_facts', 'context_compactions',
}


def _dump(path):
    with sqlite3.connect(path) as db:
        return '\n'.join(db.iterdump())


def _make_v12_database(path):
    """构造一个 v12 数据库：当前代码建库后摘除 agent 表并回退版本号。"""
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(path, 'alice')
    project = store.create_project('p')
    session = store.create_session(project)
    store.append(session, 'user', '历史消息一')
    store.append(session, 'assistant', '历史回复一')
    with sqlite3.connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        for table in AGENT_TABLES:
            db.execute(f'DROP TABLE IF EXISTS {table}')
        db.execute('PRAGMA user_version=12')
        db.commit()
    return store


def test_fresh_store_is_v13_with_agent_tables(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    with sqlite3.connect(store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 16
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert AGENT_TABLES <= tables
    assert 'run_message_links' in tables, 'S16：新库必须带 v14 归属表'


def test_v12_database_migrates_with_verified_backup_and_preserves_rows(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'db.sqlite'
    _make_v12_database(path)
    before = _dump(path)
    backup = migrate_database(path)
    assert backup is not None and backup.is_file(), '迁移必须返回一致性备份'
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 16
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert AGENT_TABLES <= tables
        assert 'run_message_links' in tables, 'S16：v12 库迁移后必须带 v14 归属表'
        texts = [row[0] for row in db.execute('SELECT text FROM messages ORDER BY id')]
    assert texts == ['历史消息一', '历史回复一'], '迁移不得改写旧消息'
    # 备份内容与迁移前一致
    assert _dump(backup) == before
    # 幂等：再次迁移是无操作
    assert migrate_database(path) is None


def test_rollback_restores_pre_migration_content(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'db.sqlite'
    _make_v12_database(path)
    before = _dump(path)
    backup = migrate_database(path)
    assert backup is not None
    # 回滚：用备份覆盖迁移后的库
    shutil.copyfile(backup, path)
    assert _dump(path) == before, '回滚后逻辑内容必须与迁移前一致'
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 12
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
