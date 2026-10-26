"""Version-pinned financial data adapters shared with fuyao-finance 1.1.1.

No MCP process, desktop credential store or per-user server filesystem is used.
"""
import asyncio
import json
from pathlib import Path
from .quote_fast import latest_quote
import threading
import time

from jsonschema import Draft202012Validator, FormatChecker

from .fuyao_core import TOOLS, Api, QueryError, batch, collect
from .macro_core import MACRO_TOOLS, MacroApi


def obj(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {},
            'required': required or [], 'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 128}
_CATALOG = json.loads(Path(__file__).with_name('plugin_catalog.json').read_text(encoding='utf-8'))
HELPERS = _CATALOG['helpers']
OFFICIAL = _CATALOG['official']



def tools():
    result = {name: {'name': name, 'description': item.get('title', name) + ' ' +
                    item['description'], 'inputSchema': item['inputSchema']}
              for name, item in TOOLS.items()}
    result.update({name: {'name': name, 'description': desc, 'inputSchema': schema}
                   for name, (desc, schema) in {**MACRO_TOOLS, **HELPERS, **OFFICIAL}.items()})
    return result


def validate(name, arguments):
    catalog = tools()
    if name not in catalog:
        raise QueryError('UNKNOWN_TOOL', '未登记的数据查询工具。')
    if list(Draft202012Validator(catalog[name]['inputSchema'],
                                format_checker=FormatChecker()).iter_errors(arguments)):
        raise QueryError('INVALID_ARGUMENT', '数据查询参数不符合接口要求。')


class DataGateway:
    """One shared gate across request threads; API-key requests share throttling.

    A request owns its event loop and clients, avoiding cross-loop AsyncClient reuse.
    The deployed application remains single-process as required by the platform.
    """
    def __init__(self, official=None):
        self.official = official
        self.lock = threading.Lock()
        self.cooldown_until = 0.0
        self.last = 0.0

    def query(self, name, arguments, key=None, *, before_request=None):
        validate(name, arguments)
        if before_request is not None:
            before_request()
        if name in OFFICIAL:
            if name == 'fuyao_ifind_status':
                return {'source':'official_ifind', 'configured':self.official is not None, 'live_access_verified':False}
            if self.official is None:
                raise QueryError('OFFICIAL_UNAVAILABLE', 'Official worker is not configured')
            return self.official(name, arguments)
        if name == 'fuyao_status':
            return {'version': '1.1.1', 'api_key_configured': bool(key),
                    'public_tools': len(TOOLS), 'macro_tools': len(MACRO_TOOLS)}
        if name == 'fuyao_tool_help':
            item = tools().get(arguments['tool'])
            if item is None:
                raise QueryError('UNKNOWN_TOOL', '未登记的数据查询工具。')
            return item
        if name in MACRO_TOOLS:
            return asyncio.run(self._macro(name, arguments, before_request))
        with self.lock:
            remaining = self.cooldown_until - time.monotonic()
            if remaining > 0:
                raise QueryError('RATE_LIMITED', '共享数据接口正在限流，请稍后再试。')
            time.sleep(max(0, 0.4 - (time.monotonic() - self.last)))
            try:
                return asyncio.run(self._company(name, arguments, key, before_request))
            except QueryError as exc:
                if exc.payload['code'] == 'RATE_LIMITED':
                    self.cooldown_until = time.monotonic() + exc.payload.get('retry_after_seconds', 30)
                raise
            finally:
                self.last = time.monotonic()

    async def _macro(self, name, arguments, before_request):
        api = MacroApi(before_request=before_request)
        try:
            return await asyncio.wait_for(api.call(name, arguments), 90)
        finally:
            await api.close()

    async def _company(self, name, arguments, key, before_request):
        api = Api(key_loader=lambda: key, before_request=before_request)
        try:
            if name == 'fuyao_latest_quote':
                return await latest_quote(api, arguments['query'])
            if name == 'fuyao_query_batch':
                return await batch(api, arguments['requests'])
            if name == 'fuyao_collect_pages':
                return await collect(api, arguments['tool'], arguments['arguments'],
                                     arguments['mode'], arguments['items_path'],
                                     arguments.get('cursor_parameter'), arguments.get('next_cursor_path'),
                                     arguments.get('max_pages', 5))
            return await api.query(name, arguments)
        finally:
            # Batch/page helpers return structured failures instead of raising.
            # Carry their HTTP client's Retry-After into the shared-key gate too.
            self.cooldown_until = max(self.cooldown_until, api.cooldown_until)
            await api.close()
