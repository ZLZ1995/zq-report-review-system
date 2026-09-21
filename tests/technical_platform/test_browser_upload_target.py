import pytest


def test_oa_target_is_stable_across_display_query_and_not_an_api_work_order_id():
    from asset_based_agent.technical_platform.browser_upload_target import (
        upload_target_key,
    )
    first = upload_target_key('https://zhongqinoa01.com/projects/20/flow?fromTodo=1')
    assert first == upload_target_key('https://zhongqinoa01.com/projects/20/flow?todoPanel=review#details')
    assert first != upload_target_key('https://zhongqinoa01.com/projects/21/flow')
    assert first != upload_target_key('https://other.example/projects/20/flow')


@pytest.mark.parametrize('url', ['http://example.com', 'file:///D:/data',
                               'https://user:password@example.com',
                               'https://zhongqinoa01.com/projects/not-an-id/flow'])
def test_upload_target_rejects_unsafe_or_unknown_oa_object(url):
    from asset_based_agent.technical_platform.browser_upload_target import (
        upload_target_key,
    )
    with pytest.raises(ValueError):
        upload_target_key(url)
