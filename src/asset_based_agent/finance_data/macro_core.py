"""Public macro data. Independent clients never receive Fuyao credentials."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from .fuyao_core import QueryError

NBS = 'https://data.stats.gov.cn/dg/website/publicrelease/web/external'
LPR = 'https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis'
CATALOG = json.loads((Path(__file__).parent / 'data/macro-catalog.json').read_text(encoding='utf-8'))
INDICATORS = {x['id']: x for x in CATALOG['indicators']}


def today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def obj(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}


def choice(values):
    return {'type': 'string', 'enum': values}


TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 100}
PERIOD = {'type': 'string', 'pattern': r'^\d{4}(-\d{2}|-Q[1-4])?$'}
REGION = {'type': 'string', 'minLength': 1, 'maxLength': 30, 'description': '全国、省级官方名称或12位行政区划代码；城市可传代码。无数据不替代为省级。'}
MACRO_TOOLS = {
    'macro_indicator_search': ('搜索统计局价格、工资指标目录，返回指标ID、官方名称、基期、频率。目录不是地区覆盖承诺。', obj({
        'keyword': TEXT, 'category': choice(['cpi', 'ppi', 'wage']), 'frequency': choice(['MM', 'YY']),
        'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['keyword'])),
    'macro_regions': ('读取统计局省级地区名称和代码；市级数据须查对应地区，不用省级代替。', obj()),
    'macro_series': ('按已核验指标ID和地区读取统计局历史序列。保留缺项、基期、单位；指数减100得到相同口径涨跌幅。', obj({
        'indicator_id': {'type': 'string', 'enum': list(INDICATORS)}, 'region': REGION,
        'start': PERIOD, 'end': PERIOD}, ['indicator_id', 'region', 'start', 'end'])),
    'macro_prices': ('查询CPI/PPI月度同比环比或年度同比。季度返回三个月明细及季末相对上季末的链式变动，绝不称作官方季度平均环比。', obj({
        'indicator': choice(['CPI', 'PPI']), 'frequency': choice(['monthly', 'quarterly', 'annual']),
        'region': REGION, 'start': PERIOD, 'end': PERIOD}, ['indicator', 'frequency', 'region', 'start', 'end'])),
    'macro_wages': ('查询全国/地区私营或非私营就业人员年平均工资，按官方行业名称筛选。货币/实际工资指数严格分开；缺项提供地方官方检索建议。', obj({
        'ownership': choice(['private', 'non_private']), 'metric': choice(['average_wage', 'nominal_index', 'real_index']),
        'industry': {'type': 'string', 'maxLength': 80, 'description': '官方行业名称，如制造业；全行业省略或填全部。'},
        'region': REGION, 'start': PERIOD, 'end': PERIOD}, ['ownership', 'metric', 'region', 'start', 'end'])),
    'macro_lpr': ('中国货币网官方LPR：1年期、5年期以上。日期范围历史查询或as_of指定日期最近已公布值；按年分段，非贷款基准利率。', obj({
        'start': {'type': 'string', 'format': 'date'}, 'end': {'type': 'string', 'format': 'date'},
        'as_of': {'type': 'string', 'format': 'date'}})),
}
# IDs are selected from search output; avoid putting a 936-value enum in each tool listing.
MACRO_TOOLS['macro_series'][1]['properties']['indicator_id'] = {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}


def number(value):
    if value is None or str(value).strip() in ('', '-', '--', '…', 'null'):
        return None
    try:
        n = Decimal(str(value))
        return float(n) if n.is_finite() else None
    except InvalidOperation:
        raise QueryError('SOURCE_FORMAT', '官方数值格式发生变化，未将其当作零。')


def periods(start, end, frequency):
    pattern = {'MM': r'^\d{4}-(0[1-9]|1[0-2])$', 'YY': r'^\d{4}$', 'SS': r'^\d{4}-Q[1-4]$'}[frequency]
    if not re.fullmatch(pattern, start) or not re.fullmatch(pattern, end) or start > end:
        raise QueryError('INVALID_ARGUMENT', '时间格式或顺序错误：月YYYY-MM，年YYYY，季度YYYY-Q1。')
    if not (1900 <= int(start[:4]) <= int(end[:4]) <= today().year):
        raise QueryError('INVALID_ARGUMENT', '年份必须在1900年至当前年份之间。')
    result = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        for n in range(1, {'YY': 1, 'MM': 12, 'SS': 4}[frequency] + 1):
            s = str(y) if frequency == 'YY' else f'{y}-Q{n}' if frequency == 'SS' else f'{y}-{n:02d}'
            if start <= s <= end:
                result.append(s)
    if len(result) > 600:
        raise QueryError('INVALID_ARGUMENT', '单次最多600个统计期间，请缩小范围。')
    return result


def stamp(source, **kwargs):
    return dict(source=source, retrieved_at=datetime.now(timezone.utc).isoformat(), **kwargs)


def search(keyword, category=None, frequency=None, offset=0, limit=30):
    tokens = keyword.replace('CPI', '居民消费价格').replace('PPI', '工业生产者出厂价格').split()
    rows = [x for x in INDICATORS.values() if all(t in x['name'] for t in tokens)
            and (not category or x['category'] == category) and (not frequency or x['frequency'] == frequency)]
    return {'source': CATALOG['source'], 'catalog_reviewed_on': CATALOG['reviewed_on'], 'total': len(rows),
                'offset': offset, 'next_offset': offset+limit if offset+limit < len(rows) else None,
                'indicators': rows[offset:offset+limit]}


class MacroApi:
    def __init__(self, client=None, before_request=None):
        self.client = client or httpx.AsyncClient(timeout=25, follow_redirects=False,
                                                  headers={'User-Agent': 'FuyaoFinanceMacro/1.1'})
        self._lock = asyncio.Lock()
        self._regions = None
        self.before_request = before_request

    async def close(self):
        await self.client.aclose()

    async def request(self, path, payload=None, params=None, lpr=False):
        url = LPR if lpr else NBS + path
        async with self._lock:
            if self.before_request is not None:
                self.before_request()
            try:
                if payload is not None or lpr:
                    response = await self.client.post(url, json=payload, params=params)
                else:
                    response = await self.client.get(url, params=params)
                response.raise_for_status()
                result = response.json()
            except (httpx.HTTPError, ValueError):
                raise QueryError('MACRO_SOURCE_UNAVAILABLE', '公开数据源连接失败或格式变化；没有返回缓存旧值冒充最新值。')
            finally:
                await asyncio.sleep(0.15)
        if not isinstance(result, dict) or (not lpr and result.get('success') is not True):
            raise QueryError('MACRO_SOURCE_ERROR', '官方数据源未返回成功结果。')
        if lpr and (str(result.get('head', {}).get('rep_code')) != '200' or result.get('data', {}).get('message')):
            raise QueryError('MACRO_SOURCE_ERROR', 'LPR数据源拒绝本次查询或限制日期范围。')
        return result

    async def regions(self):
        if self._regions is None:
            r = await self.request('/getAllProvince')
            if not isinstance(r.get('data'), list):
                raise QueryError('SOURCE_FORMAT', '地区目录格式改变。')
            self._regions = [{'text': '全国', 'value': '000000000000'}] + r['data']
        return self._regions

    async def region(self, name):
        rows = await self.regions()
        exact = [x for x in rows if name in (x['text'], x['value'])]
        if len(exact) == 1:
            return exact[0]
        if re.fullmatch(r'\d{12}', name):
            return {'text': '行政区划代码' + name, 'value': name}
        raise QueryError('REGION_NOT_RESOLVED', '请用macro_regions返回的官方名称或12位地区代码；市级须核对代码，不能默认替换为所在省。')

    async def series(self, indicator_id, region, start, end):
        spec = INDICATORS.get(indicator_id)
        if not spec:
            raise QueryError('UNKNOWN_INDICATOR', '请先调用macro_indicator_search选择指标。')
        wanted = periods(start, end, spec['frequency'])
        area = await self.region(region)
        encode = lambda x: x.replace('-', '') + spec['frequency']
        payload = {'id': spec['id'], 'cid': spec['cid'], 'rootId': spec['root_id'], 'da': area['value'], 'dt': '',
                       'dts': [encode(start) + '-' + encode(end)]}
        raw = (await self.request('/getEsDataByIndicatorIdAndDa', payload=payload)).get('data')
        if not isinstance(raw, list):
            raise QueryError('SOURCE_FORMAT', '时间序列格式改变。')
        observed = {}
        for row in raw:
            dt = str(row.get('dt', ''))
            if row.get('code') != area['value'] or not dt.endswith(spec['frequency']):
                raise QueryError('SOURCE_SCOPE_MISMATCH', '返回地区或频率与请求不符，已停止。')
            t = dt[:4] if spec['frequency'] == 'YY' else dt[:4] + '-' + dt[4:6]
            if t not in wanted:
                continue
            val = number(row.get('v'))
            item = {'period': t, 'value': val, 'raw_value': row.get('v'), 'unit': row.get('unit') or None,
                        'status': 'available' if val is not None else 'missing'}
            if re.search(r'\((上月|上年|上年同月|上年同期)=100\)', spec['name']) and val is not None:
                item['change_pct'] = float(Decimal(str(row['v'])) - Decimal(100))
                item['change_formula'] = '官方指数-100；与指标基期口径一致'
            if t in observed and observed[t] != item:
                raise QueryError('SOURCE_CONFLICT', '同期间存在冲突值，未自动择一。')
            observed[t] = item
        rows = [observed.get(t, {'period': t, 'value': None, 'unit': None, 'status': 'missing'}) for t in wanted]
        missing = [x['period'] for x in rows if x['value'] is None]
        result = stamp('https://data.stats.gov.cn/', indicator=spec, region=area, observations=rows,
                       missing_periods=missing, complete=not missing, request=payload,
                       api_source=NBS+'/getEsDataByIndicatorIdAndDa')
        if missing:
            result['next_step'] = '在对应地方统计局/统计年鉴核查缺项；不得用全国、其他地区或其他单位性质代替。'
            result['suggested_search'] = f"{area['text']} {spec['name']} {start} {end} site:gov.cn"
        return result

    async def prices(self, indicator, frequency, region, start, end):
        name = {'CPI': '居民消费价格指数', 'PPI': '工业生产者出厂价格指数'}[indicator]
        freq = {'monthly': 'MM', 'annual': 'YY', 'quarterly': 'SS'}[frequency]
        requested = periods(start, end, freq)
        a, b = start, end
        if frequency == 'quarterly':
            a = f'{start[:4]}-{(int(start[-1])-1)*3+1:02d}'
            b = f'{end[:4]}-{int(end[-1])*3:02d}'
        bases = ['上年=100'] if frequency == 'annual' else ['上年同月=100', '上月=100', '上年同期=100']
        series = []
        for basis in bases:
            found = [x for x in INDICATORS.values() if x['name'] == f'{name} ({basis})']
            if len(found) != 1:
                raise QueryError('CATALOG_AMBIGUOUS', '指标目录不存在唯一总指数，请先搜索并指定指标ID。')
            series.append(await self.series(found[0]['id'], region, a, b))
        result = stamp('https://data.stats.gov.cn/', indicator=name, requested_frequency=frequency,
                       series=series, complete=all(x['complete'] for x in series))
        if frequency == 'quarterly':
            result['monthly_detail_complete'] = result['complete']
            result['complete'] = False
            result['official_quarterly_value_available'] = False
            result['note'] = '返回季度内月度明细。累计同比不是单季同比；链式结果是季末相对上季末，不是季度平均价格环比。'
            mom = {x['period']: x['value'] for x in series[1]['observations']}
            derived = []
            for q in requested:
                months = [f'{q[:4]}-{n:02d}' for n in range((int(q[-1])-1)*3+1, int(q[-1])*3+1)]
                vals = [mom.get(m) for m in months]
                value = None
                if all(v is not None for v in vals):
                    product = Decimal(1)
                    for v in vals:
                        product *= Decimal(str(v))/100
                    value = float((product-1)*100)
                derived.append({'period': q, 'quarter_end_vs_previous_quarter_end_pct': value,
                                    'method': '三个官方月度环比指数/100相乘后减1，再乘100；受原始四舍五入影响',
                                    'official': False, 'constituent_months': months})
            result['derived'] = derived
        return result

    async def wages(self, ownership, metric, region, start, end, industry=''):
        periods(start, end, 'YY')
        prefix = '' if industry in ('', '全部') else industry
        scope = '城镇私营' if ownership == 'private' else '城镇非私营'
        tail = {'average_wage': '平均工资 (元)', 'nominal_index': '平均货币工资指数 (上年=100)',
                'real_index': '平均实际工资指数 (上年=100)'}[metric]
        name = prefix + scope + '单位就业人员' + tail
        found = [x for x in INDICATORS.values() if x['name'] == name and x['frequency'] == 'YY']
        if not found:
            return stamp('https://data.stats.gov.cn/', status='not_in_reviewed_catalog', complete=False,
                         requested_indicator=name, region=region, start=start, end=end,
                         suggested_search=f'{region} {name} {start} {end} site:gov.cn',
                         note='目录缺项不代表官方未发布；继续核查地方统计局/统计年鉴。未以非私营、全国或其他工资指标替代。')
        # Identically named official catalog entries can cover different periods. Preserve them separately.
        results = [await self.series(x['id'], region, start, end) for x in found]
        return stamp('https://data.stats.gov.cn/', requested_indicator=name, series=results,
                     complete=any(x['complete'] for x in results),
                     note='同名目录分别返回，不合并冲突值；工资金额的简单比值不自动冒充官方可比口径工资指数。')

    async def lpr(self, start=None, end=None, as_of=None):
        try:
            if as_of and (start or end):
                raise ValueError()
            if as_of:
                last = date.fromisoformat(as_of)
                first = last - timedelta(days=365)
            elif start and end:
                first, last = date.fromisoformat(start), date.fromisoformat(end)
            elif not start and not end:
                last = today()
                first = last - timedelta(days=365)
            else:
                raise ValueError()
            if first > last or last > today() or first.year < 2013 or last.year-first.year > 20:
                raise ValueError()
        except ValueError:
            raise QueryError('INVALID_ARGUMENT', '提供有效start/end或单独as_of；不得查询未来日期，最多20年，起始年份不早于2013。')
        rows, requests = [], []
        cursor = first
        while cursor <= last:
            stop = min(date(cursor.year, 12, 31), last)
            params = {'lang': 'CN', 'strStartDate': cursor.isoformat(), 'strEndDate': stop.isoformat()}
            data = await self.request('', params=params, lpr=True)
            if not isinstance(data.get('records'), list):
                raise QueryError('SOURCE_FORMAT', 'LPR返回格式改变。')
            for x in data['records']:
                d = date.fromisoformat(x['showDateCN'])
                if not cursor <= d <= stop:
                    raise QueryError('SOURCE_SCOPE_MISMATCH', 'LPR返回日期不在请求范围。')
                rows.append({'date': d.isoformat(), 'one_year_pct': number(x.get('1Y')), 'five_year_plus_pct': number(x.get('5Y'))})
            requests.append(params)
            cursor = stop + timedelta(days=1)
        rows.sort(key=lambda x: x['date'])
        if as_of:
            rows = rows[-1:]
        return stamp('https://www.chinamoney.com.cn/chinese/bklpr/', api_source=LPR, unit='%',
                     terms={'one_year_pct': '1年期', 'five_year_plus_pct': '5年期以上'}, as_of=as_of,
                     observations=rows, status='available' if rows else 'no_data', requests=requests,
                     note='as_of取当日或此前最近一次公布值；不代表具体贷款合同执行利率。5年期以上早期缺值不替换为贷款基准利率。')

    async def call(self, name, arguments):
        if name == 'macro_indicator_search':
            return search(**arguments)
        if name == 'macro_regions':
            return stamp('https://data.stats.gov.cn/', regions=await self.regions(),
                         note='此目录为省级名称，不表示每个指标在每个地区均有数据；城市请核对12位代码。')
        method = {'macro_series': self.series, 'macro_prices': self.prices, 'macro_wages': self.wages, 'macro_lpr': self.lpr}[name]
        return await method(**arguments)
