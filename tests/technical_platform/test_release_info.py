import httpx
import pytest

from asset_based_agent.technical_platform.release_info import (
    CLIENT_VERSION,
    inspect_server,
    local_release,
)


def test_release_identity_matches_schema_11_delivery():
    from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION

    assert CLIENT_VERSION == '0.2.10'
    assert SCHEMA_VERSION == 11


def test_local_release_contains_actual_rule_hash():
    info = local_release()
    assert info["client_version"]
    assert len(info["review_rules_sha256"]) == 64
    assert info["review_skill_version"]


def test_local_release_includes_external_inventory_without_rules(tmp_path):
    from asset_based_agent.technical_platform.release_info import release_details
    from asset_based_agent.technical_platform.skill_installation import (
        SkillInstallation,
    )
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    SkillInstallation(store)
    info = local_release(store=store)
    assert info['external_skills'] == []
    assert info['external_skills_status'] == 'checked'
    assert '执行授权' in release_details(info)


def test_version_inspection_does_not_initialize_external_skill_tables(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    with store.connect() as db:
        before = db.execute('SELECT name FROM sqlite_master ORDER BY name').fetchall()
    assert local_release(store=store)['external_skills_status'] == 'unavailable'
    with store.connect() as db:
        assert db.execute('SELECT name FROM sqlite_master ORDER BY name').fetchall() == before


def test_local_release_reports_all_builtin_skills_and_verified_templates():
    from asset_based_agent.technical_platform.generation import locked_template
    from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION
    from asset_based_agent.technical_platform.skills import BUILTINS, GENERATORS, digest
    info = local_release()
    assert info['local_schema_version'] == SCHEMA_VERSION
    assert {s['id'] for s in info['skills']} == {s.id for s in BUILTINS}
    assert info['protocol_version'] == 1
    indexed = {s['id']: s for s in info['skills']}
    for skill in GENERATORS:
        item = indexed[skill.id]
        assert item['status'] == 'verified'
        assert item['template_sha256'] == digest(locked_template(skill.id))
        assert len(item['bundle_sha256']) == 64


def test_missing_template_is_reported_without_hiding_client_version(monkeypatch):
    from asset_based_agent.technical_platform import generation
    def missing(_skill):
        raise ValueError('private path and secret must not leak')
    monkeypatch.setattr(generation, 'locked_template', missing)
    info = local_release()
    assert info['client_version']
    generators = [s for s in info['skills'] if s['id'] in generation.INPUT_ROLES]
    assert all(s['status'] == 'unavailable_or_changed' for s in generators)
    assert 'private' not in str(info)


@pytest.mark.parametrize("supported", [True, False])
def test_protocol_check_does_not_invent_server_build_version(supported):
    def handle(request):
        assert str(request.url) == "https://server.test/openapi.json"
        return httpx.Response(200, json={
            "info": {"version": "0.1.0"},
            "components": {"schemas": {"ReviewJobCreateRequest": {"properties": {
                **({"user_request": {"type": "string"}} if supported else {})
            }}}},
        })
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        info = inspect_server("https://server.test/api/v1", client=client)
    assert info["user_request_supported"] is supported
    assert info["server_api_version"] == "0.1.0"
    assert info["server_build"] == "未提供"


def test_protocol_inspection_reads_explicit_metadata_and_build():
    def handle(request):
        if request.url.path == '/openapi.json':
            return httpx.Response(200, json={'paths': {'/api/v1/capabilities': {'get': {}}}})
        assert request.url.path == '/api/v1/capabilities'
        return httpx.Response(200, json={
            'schema_version': 1, 'protocol_version': 1, 'build_sha': 'b' * 40,
            'capabilities': {'skill_routing': 1},
        })
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        info = inspect_server('https://server.test', client=client)
    assert info['server_build'] == 'b' * 40
    assert info['capabilities'] == {'skill_routing': 1}
    assert info['protocol_version'] == 1


def test_protocol_inspection_reads_current_signed_release_metadata():
    def handle(request):
        if request.url.path == '/openapi.json':
            return httpx.Response(200, json={'paths': {'/api/v1/capabilities': {'get': {}}}})
        if request.url.path == '/api/v1/capabilities':
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                             'build_sha': 'b' * 40, 'capabilities': {'client_release': 1}})
        return httpx.Response(200, json={'status': 'stable', 'version': '0.2.7', 'sequence': 2,
                                         'manifest_sha256': 'a' * 64, 'manifest': {'payload': {}, 'signature': 'x'}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        info = inspect_server('https://server.test', client=client)
    assert info['current_release']['version'] == '0.2.7'


def test_unknown_metadata_schema_is_not_treated_as_compatible():
    def handle(request):
        if request.url.path == '/openapi.json':
            return httpx.Response(200, json={'paths': {'/api/v1/capabilities': {'get': {}}}})
        return httpx.Response(200, json={'schema_version': 999})
    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as client,
        pytest.raises(ValueError, match='协议'),
    ):
        inspect_server('https://server.test', client=client)


def test_version_panel_shows_verified_build_not_hardcoded_unknown():
    from types import SimpleNamespace

    from asset_based_agent.technical_platform.app import PlatformWindow
    texts = []
    details = []
    visibility = []
    fake = SimpleNamespace(
        store=None,
        version_label=SimpleNamespace(setText=texts.append, setToolTip=details.append),
        update_button=SimpleNamespace(setVisible=visibility.append),
        available_update=None,
    )
    PlatformWindow.versions_checked(fake, {'user_request_supported': True, 'server_api_version': '0.1.0',
                                          'server_build': 'c' * 40, 'protocol_version': 1})
    assert 'c' * 40 in texts[0]
    assert 'template_sha256' in details[0]
    assert 'gongshang-change-history-docx' in details[0]
    assert '不代表项目已迁移' in details[0]
    assert visibility == [False]


def test_version_panel_offers_only_new_stable_signed_release():
    import hashlib
    import json
    from types import SimpleNamespace

    from asset_based_agent.technical_platform.app import PlatformWindow

    manifest = {'payload': {'version': '0.2.11', 'sequence': 6}, 'signature': 'x'}
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True).encode('ascii')
    record = {'status': 'stable', 'version': '0.2.11', 'sequence': 6,
              'manifest': manifest,
              'manifest_sha256': hashlib.sha256(encoded).hexdigest()}
    visibility = []
    fake = SimpleNamespace(
        store=None,
        version_label=SimpleNamespace(setText=lambda _text: None,
                                      setToolTip=lambda _text: None),
        update_button=SimpleNamespace(setVisible=visibility.append),
        available_update=None,
    )
    PlatformWindow.versions_checked(fake, {
        'user_request_supported': True,
        'server_api_version': '1',
        'server_build': 'b' * 40,
        'protocol_version': 1,
        'current_release': record,
    })
    assert fake.available_update == record
    assert visibility == [True]
