from asset_based_agent.technical_platform.business_tools.service import (
    BusinessRunService,
)
from asset_based_agent.technical_platform.business_tools.tools import business_tools
from asset_based_agent.technical_platform.store import PlatformStore


def test_read_project_file_is_scoped_and_bounded(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('alpha\nbeta\ngamma', encoding='utf-8')
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    from asset_based_agent.technical_platform.skills import digest
    file_id = store.add_file(project, source, digest(source))
    service = BusinessRunService(store, session)
    payload = service.read_file_content(file_id, max_chars=5)

    assert payload['content'] == 'alpha'
    assert payload['truncated'] is True
    reader = next(tool for tool in business_tools(service)
                  if tool.descriptor.name == 'read_project_file')
    assert reader.descriptor.risk == 'local_readonly'
