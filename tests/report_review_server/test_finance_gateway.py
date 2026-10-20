import asyncio

import httpx
import pytest

from asset_based_agent.finance_data import DataGateway, QueryError, tools, validate
from asset_based_agent.finance_data.fuyao_core import Api, batch, collect
from asset_based_agent.finance_data.macro_core import MacroApi


def test_full_catalog_is_closed_and_helper_bounds_are_enforced():
    assert len(tools()) == 113
    assert len([name for name in tools() if name.startswith('get_')]) == 103
    with pytest.raises(QueryError):
        validate('fuyao_collect_pages', {'tool': 'anything', 'arguments': {}, 'mode': 'offset',
                                       'items_path': 'data.item', 'max_pages': 21})
    with pytest.raises(QueryError):
        validate('get_meta_tickers_search', {'q': 'test', 'url': 'https://other.example'})


def test_credentials_are_sent_only_to_fixed_company_endpoint_and_redacted():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == 'fuyao.aicubes.cn'
        assert request.headers['X-api-key'] == 'synthetic-key'
        return httpx.Response(200, json={'code': 0, 'data': {'echo': 'synthetic-key'}})
    async def scenario():
        api = Api(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                  key_loader=lambda: 'synthetic-key', interval=0)
        try:
            result = await api.query('get_a_share_calendar_trading_days', {})
            assert result['response']['data']['echo'] == '[REDACTED]'
        finally:
            await api.close()
    asyncio.run(scenario())
    assert len(requests) == 1


def test_paginated_result_is_returned_in_full_without_server_file_paths():
    def handler(request):
        return httpx.Response(200, json={'code': 0, 'data': {'item': [
            {'offset': int(request.url.params['offset']), 'value': 123}]}})
    async def scenario():
        api = Api(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                  key_loader=lambda: 'synthetic-key', interval=0)
        try:
            result = await collect(api, 'get_a_share_prices_snapshot', {'limit': 1},
                                   'offset', 'data.item', max_pages=2)
            assert result['rows_fetched'] == 2
            assert len(result['pages']) == 2
            assert result['complete'] is False
            assert 'saved_file' not in result
        finally:
            await api.close()
    asyncio.run(scenario())


def test_batch_rechecks_cancellation_before_each_http_request():
    calls = []
    class Cancelled(Exception):
        pass
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'code': 0, 'data': []})
    def check():
        if calls:
            raise Cancelled()
    async def scenario():
        api = Api(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                  key_loader=lambda: 'synthetic-key', interval=0, before_request=check)
        try:
            with pytest.raises(Cancelled):
                await batch(api, [{'tool': 'get_a_share_calendar_trading_days'}] * 3)
        finally:
            await api.close()
    asyncio.run(scenario())
    assert len(calls) == 1


def test_lpr_does_not_receive_company_key_and_preserves_missing_term():
    def handler(request):
        assert request.url.host == 'www.chinamoney.com.cn'
        assert 'x-api-key' not in request.headers
        return httpx.Response(200, json={'head': {'rep_code': '200'}, 'records': [
            {'showDateCN': '2025-01-20', '1Y': '3.1', '5Y': '--'}]})
    async def scenario():
        api = MacroApi(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await api.call('macro_lpr', {'start': '2025-01-01', 'end': '2025-01-31'})
            assert result['observations'][0]['one_year_pct'] == 3.1
            assert result['observations'][0]['five_year_plus_pct'] is None
        finally:
            await api.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('helper', ['fuyao_query_batch', 'fuyao_collect_pages'])
def test_helper_rate_limit_blocks_following_shared_key_request(monkeypatch, helper):
    import time

    import asset_based_agent.finance_data as gateway_module
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '60'})
    def api_factory(**kwargs):
        return Api(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                   interval=0, **kwargs)
    monkeypatch.setattr(gateway_module, 'Api', api_factory)
    gateway = DataGateway()
    name = 'get_a_share_prices_snapshot'
    arguments = ({'requests': [{'tool': name, 'arguments': {'limit': 1}}]}
                 if helper == 'fuyao_query_batch' else
                 {'tool': name, 'arguments': {'limit': 1}, 'mode': 'offset', 'items_path': 'data.item'})
    gateway.query(helper, arguments, 'synthetic-key')
    assert gateway.cooldown_until > time.monotonic() + 55
    with pytest.raises(QueryError) as error:
        gateway.query(name, {}, 'synthetic-key')
    assert error.value.payload['code'] == 'RATE_LIMITED'
    assert len(calls) == 1
