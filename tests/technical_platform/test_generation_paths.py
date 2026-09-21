import pytest

from asset_based_agent.technical_platform.generation_paths import (
    generation_work_directory,
)


def test_step_names_are_hashed_and_existing_step_cannot_be_reused(tmp_path):
    first = generation_work_directory(tmp_path, 'task', '../../outside', create=True)
    second = generation_work_directory(tmp_path, 'task', 'other', create=True)
    assert first.parent == second.parent == tmp_path / 'runs' / 'task' / 'steps'
    assert first != second and first.is_dir() and second.is_dir()
    (first / 'sentinel').write_bytes(b'preserve')
    with pytest.raises(FileExistsError):
        generation_work_directory(tmp_path, 'task', '../../outside', create=True)
    assert (first / 'sentinel').read_bytes() == b'preserve'


@pytest.mark.parametrize('run_id', ['../outside', 'D:/outside', '', '..'])
def test_run_identity_cannot_escape_output_root(tmp_path, run_id):
    with pytest.raises(ValueError):
        generation_work_directory(tmp_path, run_id, 'one', create=True)
    assert not list(tmp_path.iterdir())
