import pytest


def library(tmp_path, owner='alice', environment='production'):
    from asset_based_agent.technical_platform.browser_library import BrowserLibrary
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    program, data = tmp_path/'program', tmp_path/'data'
    program.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    prefs = StoragePreferences(tmp_path/'index.sqlite', program)
    prefs.select(owner, data)
    return BrowserLibrary(prefs, owner, environment=environment)


def test_bookmarks_home_persist_and_accounts_are_isolated(tmp_path):
    first = library(tmp_path)
    assert first.home() == 'about:blank'
    assert first.permission_mode() == 'risk'
    first.set_permission_mode('full')
    first.save('OA', 'https://zhongqinoa01.com/')
    first.set_home('https://example.com/')
    reopened = library(tmp_path)
    assert reopened.bookmarks() == [('OA', 'https://zhongqinoa01.com/')]
    assert reopened.home() == 'https://example.com/'
    assert reopened.permission_mode() == 'full'
    assert library(tmp_path, 'bob').bookmarks() == []
    assert library(tmp_path, 'bob').permission_mode() == 'risk'
    assert library(tmp_path, environment='test').home() == 'about:blank'
    assert library(tmp_path, environment='test').permission_mode() == 'full'
    reopened.save('办公', 'https://zhongqinoa01.com/')
    assert reopened.bookmarks() == [('办公', 'https://zhongqinoa01.com/')]
    reopened.remove('https://zhongqinoa01.com/')
    assert reopened.bookmarks() == []
    reopened.set_home('about:blank')
    assert reopened.home() == 'about:blank'


@pytest.mark.parametrize('mode', ['', 'automatic', 'FULL'])
def test_library_rejects_unknown_permission_mode_without_changing_setting(tmp_path, mode):
    store = library(tmp_path)
    with pytest.raises(ValueError):
        store.set_permission_mode(mode)
    assert store.permission_mode() == 'risk'


@pytest.mark.parametrize('url', ['file:///D:/private.txt', 'javascript:alert(1)',
                                 'https://user:password@example.com', 'https://'])
def test_library_rejects_unsafe_addresses_without_changes(tmp_path, url):
    store = library(tmp_path)
    with pytest.raises(ValueError):
        store.save('example', url)
    with pytest.raises(ValueError):
        store.set_home(url)
    assert store.bookmarks() == [] and store.home() == 'about:blank'


def test_missing_data_never_recreated(tmp_path):
    store = library(tmp_path)
    store.save('example', 'https://example.com/')
    (tmp_path/'data').rename(tmp_path/'unplugged')
    with pytest.raises(OSError):
        store.bookmarks()
    assert not (tmp_path/'data').exists()
