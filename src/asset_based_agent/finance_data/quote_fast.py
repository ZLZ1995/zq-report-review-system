"""Single-call latest A-share quote; never cache market prices."""
import re
import time
from datetime import datetime, timezone, timedelta


async def latest_quote(api, query):
    query = query.strip()
    if not query:
        from .fuyao_core import QueryError
        raise QueryError('INVALID_ARGUMENT', 'query must not be blank')
    started = time.perf_counter()
    name = None
    code = query.upper()
    if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
        found = await api.query('get_meta_tickers_search', {'q': query, 'asset_type': 'a-share', 'limit': 50})
        candidates = found['response']['data'].get('item', [])
        exact = [r for r in candidates if query in (r.get('name'), r.get('ticker'), r.get('thscode'))]
        matches = exact if exact else candidates
        if len(matches) != 1:
            return {'status': 'ambiguous' if matches else 'not_found',
                    'query': query, 'candidates': matches, 'quote': None}
        code, name = matches[0]['thscode'], matches[0].get('name')
    raw = await api.query('get_a_share_prices_snapshot', {'thscodes': code})
    data = raw['response']['data']
    rows = [r for r in data.get('item', []) if r.get('thscode') == code]
    stamp = data.get('timestamp')
    as_of = None if stamp is None else datetime.fromtimestamp(stamp / 1000, timezone(timedelta(hours=8))).isoformat()
    return {'status': 'ok' if rows else 'no_data', 'name': name, 'thscode': code,
            'data_time': as_of, 'timestamp': stamp, 'timezone': 'Asia/Shanghai',
            'currency': 'CNY', 'volume_unit': 'share', 'quote': rows[0] if rows else None,
            'source': raw.get('source'), 'request_id': raw['response'].get('request_id'),
            'elapsed_ms': round((time.perf_counter() - started) * 1000)}
