"""Read-only REST adapter with a fixed destination and a reviewed tool allowlist."""
import asyncio
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from .storage import load_key

ROOT = Path(__file__).resolve().parent
BASE_URL = 'https://fuyao.aicubes.cn'
CATALOG = json.loads((ROOT / 'data/catalog.json').read_text(encoding='utf-8'))
TOOLS = {t['name']: t for t in CATALOG['tools']}


class QueryError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.payload = {'code': code, 'message': message, **details}


def clean(value, key=None):
    """Redact exact credentials from every returned or persisted structure."""
    if isinstance(value, str):
        return value.replace(key, '[REDACTED]') if key else value
    if isinstance(value, list):
        return [clean(x, key) for x in value]
    if isinstance(value, dict):
        return {clean(str(k), key): ('[REDACTED]' if str(k).lower() in ('api_key', 'x-api-key', 'authorization', 'cookie') else clean(v, key)) for k, v in value.items()}
    return value


def check_arguments(name, args):
    if name not in TOOLS:
        raise QueryError('UNKNOWN_TOOL', 'Unknown or unpublished tool.')
    errors = list(Draft202012Validator(TOOLS[name]['inputSchema'], format_checker=FormatChecker()).iter_errors(args))
    if errors:
        e = errors[0]
        raise QueryError('INVALID_ARGUMENT', f'Invalid parameter at {".".join(map(str, e.path)) or "arguments"}; rule: {e.validator}. Use fuyao_tool_help.')
    if 'thscode' in args and ',' in args['thscode']:
        raise QueryError('INVALID_ARGUMENT', 'thscode accepts one identifier; use fuyao_query_batch for multiple identifiers.')
    if 'start' in args or 'end' in args:
        if ('start' in args) != ('end' in args):
            raise QueryError('INVALID_ARGUMENT', 'start and end must be supplied together.')
        if args['start'] > args['end']:
            raise QueryError('INVALID_ARGUMENT', 'end must be greater than or equal to start.')
    if (name in ('get_a_share_financials_balance_sheets', 'get_a_share_financials_cash_flow_statements', 'get_a_share_financials_income_statements')
            and 'limit' in args and 'start' in args):
        raise QueryError('INVALID_ARGUMENT', 'Financial statements: limit is mutually exclusive with start/end.')
    for k, v in args.items():
        if k in ('limit', 'size', 'page') and isinstance(v, int) and v < 1:
            raise QueryError('INVALID_ARGUMENT', f'{k} must be positive.')
        if k == 'offset' and isinstance(v, int) and v < 0:
            raise QueryError('INVALID_ARGUMENT', 'offset must be nonnegative.')
    return TOOLS[name]


class Api:
    def __init__(self, client=None, key_loader=load_key, interval=0.4, sleep=asyncio.sleep, before_request=None):
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False)
        self.key_loader = key_loader
        self.interval, self.sleep = interval, sleep
        self.lock = asyncio.Lock()
        self.last = 0.0
        self.cooldown_until = 0.0
        self.before_request = before_request

    async def close(self):
        await self.client.aclose()

    async def query(self, name, args):
        tool = check_arguments(name, args)
        try:
            key = self.key_loader()
        except Exception:  # noqa: BLE001 - credential boundary must never expose secret details
            raise QueryError('CREDENTIAL_ERROR', 'Cannot read local credential; rerun configure-key.cmd.') from None
        if not key:
            raise QueryError('MISSING_API_KEY', 'Run configure-key.cmd locally or set FUYAO_API_KEY, then retry. Do not paste keys into chat.')
        params = {k: ('true' if v else 'false') if isinstance(v, bool) else v for k, v in args.items()}
        async with self.lock:
            remaining = self.cooldown_until - time.monotonic()
            if remaining > 0:
                raise QueryError('RATE_LIMITED', 'Upstream cooldown is active; retry later.', retry_after_seconds=round(remaining + 1))
            delay = self.interval - (time.monotonic() - self.last)
            if delay > 0:
                await self.sleep(delay)
            if self.before_request is not None:
                self.before_request()
            try:
                response = await self.client.get(BASE_URL + tool['path'], params=params,
                                                 headers={'X-api-key': key, 'Accept': 'application/json'})
            except httpx.TimeoutException:
                raise QueryError('TIMEOUT', 'Upstream request timed out; no automatic retry was made.') from None
            except httpx.RequestError:
                raise QueryError('NETWORK_ERROR', 'Cannot connect to the data service. Check network/proxy configuration.') from None
            finally:
                self.last = time.monotonic()
            try:
                body = response.json()
            except ValueError:
                body = None
            if response.status_code == 429 or (isinstance(body, dict) and body.get('code') == 4001):
                try:
                    cooldown = max(5, min(float(response.headers.get('Retry-After', '30')), 3600))
                except ValueError:
                    cooldown = 30
                self.cooldown_until = time.monotonic() + cooldown
                raise QueryError('RATE_LIMITED', 'Upstream rate limit reached; no immediate retry.', retry_after_seconds=cooldown,
                                 upstream=clean(body, key) if isinstance(body, dict) else None)
        if 300 <= response.status_code < 400:
            raise QueryError('REDIRECT_BLOCKED', 'Unexpected upstream redirect. Credentials were not forwarded.')
        if response.status_code >= 400:
            raise QueryError('HTTP_ERROR', 'Data service returned an HTTP error.', http_status=response.status_code,
                             upstream=clean(body, key) if isinstance(body, dict) else None)
        if not isinstance(body, dict) or 'code' not in body:
            raise QueryError('INVALID_RESPONSE', 'Expected an ApiResponse JSON object with a code field.')
        if body['code'] != 0:
            raise QueryError('UPSTREAM_ERROR', 'Data service rejected the query.', upstream=clean(body, key))
        return {'tool': name, 'source': BASE_URL + tool['path'], 'documentation': tool['source'],
                'queried_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'parameters': clean(args, key),
                'response': clean(body, key), 'scope': 'single_response; inspect upstream pagination metadata'}


def present(result, force_save=False):
    """Return full server payload; persistence belongs to the authenticated caller."""
    return result


async def batch(api, requests, save=False):
    if not 1 <= len(requests) <= 20:
        raise QueryError('INVALID_ARGUMENT', 'Batch size must be between 1 and 20.')
    # Validate all requests before making any network call.
    for req in requests:
        check_arguments(req['tool'], req.get('arguments', {}))
    results = []
    deadline = time.monotonic() + 45
    for req in requests:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            results.append({'ok': True, 'result': await asyncio.wait_for(api.query(req['tool'], req.get('arguments', {})), remaining)})
        except asyncio.TimeoutError:
            results.append({'ok': False, 'tool': req['tool'], 'error': {'code': 'TIME_BUDGET', 'message': 'Batch reached its 45-second limit; remaining requests were not attempted.'}})
            break
        except QueryError as e:
            results.append({'ok': False, 'tool': req['tool'], 'error': e.payload})
            if e.payload['code'] in ('RATE_LIMITED', 'MISSING_API_KEY', 'CREDENTIAL_ERROR') or (e.payload.get('upstream') or {}).get('code') in (2001, 2003):
                break
    return present({'results': results, 'requested': len(requests), 'attempted': len(results),
                    'succeeded': sum(r['ok'] for r in results), 'failed': sum(not r['ok'] for r in results),
                    'unattempted': len(requests) - len(results)}, force_save=save)


def at_path(data, path):
    for part in path.split('.'):
        if not isinstance(data, dict) or part not in data:
            raise QueryError('PAGINATION_CONTRACT', 'Response field path not found: ' + path)
        data = data[part]
    return data


async def collect(api, name, arguments, mode, items_path, cursor_parameter=None, next_cursor_path=None, max_pages=5):
    tool = check_arguments(name, arguments)
    params = dict(arguments)
    props = tool['inputSchema']['properties']
    if mode == 'offset':
        if not all(k in props and props[k]['type'] == 'integer' for k in ('offset', 'limit')) or 'thscodes' in params:
            raise QueryError('INVALID_ARGUMENT', 'This request does not support numeric offset/limit pagination.')
        if 'limit' not in params:
            raise QueryError('INVALID_ARGUMENT', 'Supply an explicit limit for pagination.')
        params.setdefault('offset', 0)
    elif mode == 'page':
        if 'page' not in props:
            raise QueryError('INVALID_ARGUMENT', 'This tool has no page parameter.')
        params.setdefault('page', 1)
    elif mode == 'cursor':
        if cursor_parameter not in props or not next_cursor_path:
            raise QueryError('INVALID_ARGUMENT', 'Supply documented cursor_parameter and next_cursor_path.')
    else:
        raise QueryError('INVALID_ARGUMENT', 'Unsupported pagination mode.')
    pages, seen, rows = [], set(), 0
    reason, error = 'page_limit', None
    deadline = time.monotonic() + 45
    for _ in range(max_pages):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = 'time_budget'
                break
            page = await asyncio.wait_for(api.query(name, params), remaining)
            items = at_path(page['response'], items_path)
            if not isinstance(items, list):
                raise QueryError('PAGINATION_CONTRACT', 'items_path must resolve to an array.')
            digest = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if items and digest in seen:
                reason = 'repeated_page'
                break
            seen.add(digest)
            pages.append(page)
            rows += len(items)
            if not items:
                reason = 'empty_page'
                break
            if mode == 'cursor':
                nxt = at_path(page['response'], next_cursor_path)
                if nxt is None or nxt == '':
                    reason = 'cursor_exhausted'
                    break
                if nxt == params.get(cursor_parameter):
                    reason = 'repeated_cursor'
                    break
                params[cursor_parameter] = nxt
            elif mode == 'offset':
                # Do not assume a short page is final; the server may cap page size.
                params['offset'] += len(items)
            else:
                params['page'] += 1
        except asyncio.TimeoutError:
            reason = 'time_budget'
            break
        except QueryError as e:
            reason, error = 'error', e.payload
            break
    return present({'tool': name, 'pages': pages, 'pages_fetched': len(pages), 'rows_fetched': rows,
                    'stop_reason': reason, 'complete': reason in ('empty_page', 'cursor_exhausted'),
                    'next_arguments': params, 'error': error}, force_save=True)
