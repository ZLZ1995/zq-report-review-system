"""S03：SQLite SessionRepo 专有保障——并发、崩溃安全与持久化。"""
import sqlite3
import threading


def _repo(path, owner='alice'):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    if not path.exists():
        PlatformStore(path, owner)
    return SQLiteSessionRepo(path, owner)


def test_two_processes_racing_same_lane_have_single_winner(tmp_path):
    from asset_based_agent.technical_platform.agent_core.errors import OperationBusy
    repo = _repo(tmp_path / 'db.sqlite')
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    barrier = threading.Barrier(3, timeout=60)
    outcomes = []

    def race(tag):
        barrier.wait()
        try:
            _repo(tmp_path / 'db.sqlite').begin_operation(
                's1', 'main', user_text=tag, request_id=f'r-{tag}')
            outcomes.append('ok')
        except OperationBusy:
            outcomes.append('busy')

    threads = [threading.Thread(target=race, args=(tag,)) for tag in ('a', 'b')]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ['busy', 'ok'], '同 lane 并发提交只能有一个获胜'
    assert len(repo.entries('s1', 'main')) == 1


def test_abrupt_close_mid_transaction_leaves_no_partial_data(tmp_path):
    path = tmp_path / 'db.sqlite'
    repo = _repo(path)
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    # 模拟进程死亡：写事务未提交即丢弃连接
    db = sqlite3.connect(path, timeout=15)
    db.execute('BEGIN IMMEDIATE')
    db.execute("INSERT INTO conversation_entries "
               "(id,session_id,lane_id,parent_id,sequence,entry_type,payload_json,"
               "operation_id,turn_id,schema_version,created_at) "
               "VALUES('ghost','s1','main',NULL,99,'user_message','{}',NULL,NULL,1,'t')")
    db.close()  # 未 commit，连接销毁 = 崩溃
    check = sqlite3.connect(path)
    assert check.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    assert check.execute(
        "SELECT COUNT(*) FROM conversation_entries WHERE id='ghost'").fetchone()[0] == 0
    check.close()


def test_data_survives_repo_reopen(tmp_path):
    path = tmp_path / 'db.sqlite'
    repo = _repo(path)
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    operation = repo.begin_operation('s1', 'main', user_text='持久', request_id='r1')
    repo.complete_operation(operation.id, assistant_entry_id=repo.append_entry(
        's1', 'main', 'assistant_message', {'text': '答'}).id, turn_id=None)
    reopened = _repo(path)
    entries = reopened.entries('s1', 'main')
    assert [e.entry_type for e in entries] == ['user_message', 'assistant_message']
    assert reopened.get_operation(operation.id).status == 'completed'


def test_operation_events_are_durable_and_ordered(tmp_path):
    path = tmp_path / 'db.sqlite'
    repo = _repo(path)
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    operation = repo.begin_operation('s1', 'main', user_text='一', request_id='r1')
    repo.fail_operation(operation.id, code='model.timeout', summary='t', turn_id=None)
    with sqlite3.connect(path) as db:
        rows = db.execute(
            'SELECT event_type FROM agent_operation_events WHERE operation_id=? '
            'ORDER BY sequence', (operation.id,)).fetchall()
    kinds = [row[0] for row in rows]
    assert kinds[0] == 'operation_accepted'
    assert kinds[-1] == 'operation_failed'


def test_integrity_validator_accepts_healthy_and_failed_histories(tmp_path):
    repo = _repo(tmp_path / 'db.sqlite')
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    assert repo.validate_integrity()
    operation = repo.begin_operation('s1', 'main', user_text='一', request_id='r1')
    repo.fail_operation(operation.id, code='model.timeout', summary='t',
                        turn_id=None)
    assert repo.validate_integrity(), '失败留痕不得破坏结构完整性'


def test_permission_mode_survives_reopen(tmp_path):
    repo = _repo(tmp_path / 'db.sqlite')
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    repo.set_permission_mode('s1', 'assisted')
    assert _repo(tmp_path / 'db.sqlite').session_permission_mode('s1') == 'assisted'
