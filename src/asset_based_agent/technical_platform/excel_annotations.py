"""Patch selected visible cells without resaving original workbook structures."""
import io
import posixpath
from copy import deepcopy
from uuid import uuid4
from zipfile import ZipFile

from lxml import etree as ET
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.cell_range import CellRange

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
D = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
R = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'
N = {'s': S}


def annotate_excel(source, destination, issues):
    from .annotations import _bytes, _xml
    with ZipFile(source) as archive:
        infos = archive.infolist()
        raw = {item.filename: archive.read(item) for item in infos}
    if any(name.startswith('_xmlsignatures/') for name in raw):
        raise ValueError('数字签名工作簿不支持标注')
    workbook = _xml(raw['xl/workbook.xml'])
    relationships = _xml(raw['xl/_rels/workbook.xml.rels'])
    targets = {r.get('Id'): r.get('Target') for r in relationships}
    styles = _xml(raw['xl/styles.xml'])
    fills, xfs = styles.find('s:fills', N), styles.find('s:cellXfs', N)
    fill_id = len(fills)
    fill = ET.SubElement(fills, f'{{{S}}}fill')
    pattern = ET.SubElement(fill, f'{{{S}}}patternFill', patternType='solid')
    ET.SubElement(pattern, f'{{{S}}}fgColor', rgb='FFFFFF00')
    fills.set('count', str(len(fills)))
    types = _xml(raw['[Content_Types].xml'])
    modified, applied, skipped = {}, [], []
    for sheet in workbook.findall('s:sheets/s:sheet', N):
        selected = [(n, i) for n, i in issues if (i.get('location', {}).get('table') or i.get('location', {}).get('sheet')) == sheet.get('name')]
        if not selected:
            continue
        if sheet.get('state', 'visible') != 'visible':
            skipped.extend({'issue': n, 'reason': '隐藏工作表不定位、不标注'} for n, _ in selected)
            continue
        target = targets[sheet.get(f'{{{D}}}id')]
        path = posixpath.normpath(posixpath.join('xl', target)) if not target.startswith('/') else target.lstrip('/')
        xml = _xml(raw[path])
        relpath = posixpath.join(posixpath.dirname(path), '_rels', posixpath.basename(path) + '.rels')
        rels = _xml(raw[relpath]) if relpath in raw else ET.Element(f'{{{R}}}Relationships')
        if xml.find('s:legacyDrawing', N) is not None or any(r.get('Type', '').endswith(('/comments', '/threadedComment')) for r in rels):
            skipped.extend({'issue': n, 'reason': '工作表已有批注或兼容绘图，保留原有内容，暂不追加'} for n, _ in selected)
            continue
        helper = Workbook()
        count = 0
        for number, issue in selected:
            coordinate = issue.get('location', {}).get('cell', '')
            cells = [c for c in xml.findall('.//s:sheetData/s:row/s:c', N) if c.get('r') == coordinate]
            quote = str(issue.get('original_text', '')).strip()
            merged = any(coordinate in CellRange(m.get('ref')) for m in xml.findall('s:mergeCells/s:mergeCell', N)) if coordinate else True
            if len(cells) != 1 or not quote or merged:
                skipped.append({'issue': number, 'reason': '缺少精确单元格原文，或为合并区域，未标注'})
                continue
            cell = cells[0]
            text = ''.join(cell.xpath('.//s:t/text()', namespaces=N)) or cell.findtext('s:f', namespaces=N) or cell.findtext('s:v', namespaces=N) or ''
            if cell.get('t') == 's':
                strings = _xml(raw['xl/sharedStrings.xml'])
                text = ''.join(strings[int(text)].xpath('.//s:t/text()', namespaces=N))
            if text.strip() != quote or helper.active[coordinate].comment is not None:
                skipped.append({'issue': number, 'reason': '单元格原文不匹配或重复锚点，未标注'})
                continue
            style = deepcopy(xfs[int(cell.get('s', '0'))])
            style.set('fillId', str(fill_id))
            style.set('applyFill', '1')
            cell.set('s', str(len(xfs)))
            xfs.append(style)
            nature = '待核实' if issue.get('requires_verification') else '审核意见（请核对）'
            helper.active[coordinate].comment = Comment(f"{number}｜{nature}：{issue['description']} 建议：{issue.get('recommendation', '')}", 'ZQ')
            applied.append(number)
            count += 1
        if not count:
            continue
        buffer = io.BytesIO()
        helper.save(buffer)
        with ZipFile(buffer) as package:
            comment = package.read(next(n for n in package.namelist() if n.startswith('xl/comments/') and n.endswith('.xml')))
            vml = package.read(next(n for n in package.namelist() if n.endswith('.vml')))
        identity = uuid4().hex
        comment_path, vml_path = f'xl/comments/zq{identity}.xml', f'xl/drawings/zq{identity}.vml'
        for suffix, dest in [('comments', comment_path), ('vmlDrawing', vml_path)]:
            ET.SubElement(rels, f'{{{R}}}Relationship', Id='zq' + suffix + identity,
                          Type=D + '/' + suffix, Target='/' + dest)
        legacy = ET.Element(f'{{{S}}}legacyDrawing', {f'{{{D}}}id': 'zqvmlDrawing' + identity})
        tail = next((c for c in xml if ET.QName(c).localname in {
            'legacyDrawingHF', 'picture', 'oleObjects', 'controls', 'webPublishItems', 'tableParts', 'extLst'}), None)
        xml.insert(xml.index(tail) if tail is not None else len(xml), legacy)
        ET.SubElement(types, f'{{{C}}}Override', PartName='/' + comment_path,
                      ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml')
        if not any(t.get('Extension') == 'vml' for t in types):
            ET.SubElement(types, f'{{{C}}}Default', Extension='vml', ContentType='application/vnd.openxmlformats-officedocument.vmlDrawing')
        modified.update({path: _bytes(xml), relpath: _bytes(rels), comment_path: comment, vml_path: vml})
    accounted = set(applied) | {s['issue'] for s in skipped}
    skipped.extend({'issue': n, 'reason': '工作表定位无效，未标注'} for n, _ in issues if n not in accounted)
    if not applied:
        return applied, skipped
    xfs.set('count', str(len(xfs)))
    modified.update({'xl/styles.xml': _bytes(styles), '[Content_Types].xml': _bytes(types)})
    with ZipFile(destination, 'x') as archive:
        for info in infos:
            archive.writestr(info, modified.get(info.filename, raw[info.filename]))
        for name, content in modified.items():
            if name not in raw:
                archive.writestr(name, content)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(archive.read(name) == content for name, content in raw.items() if name not in modified)
    return applied, skipped
