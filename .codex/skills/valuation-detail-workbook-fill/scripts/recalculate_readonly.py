"""Calculate in read-only Excel/WPS, then update caches without replacing formulas."""
import os
import posixpath
import tempfile
from lxml import etree as ET
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
STANDARD_ERRORS = {2000: '#NULL!', 2007: '#DIV/0!', 2015: '#VALUE!', 2023: '#REF!',
                   2029: '#NAME?', 2036: '#NUM!', 2042: '#N/A', 2043: '#GETTING_DATA'}


def create_calculation_application(dispatch=None):
    if dispatch is None:
        import win32com.client
        dispatch = win32com.client.DispatchEx
    for progid, engine in [('Excel.Application', 'Microsoft Excel'),
                           ('ket.Application', 'WPS'), ('et.Application', 'WPS')]:
        try:
            return dispatch(progid), engine
        except Exception:
            continue
    raise RuntimeError('无法启动 Microsoft Excel 或 WPS 表格的自动化组件，请安装或修复组件后重试；未发布成果')


def calculate_all(app, engine):
    # WPS supports CalculateFull; do not silently accept cached/stale values.
    if engine == 'Microsoft Excel':
        app.CalculateFullRebuild()
    else:
        app.CalculateFull()


def read_formula_values(sheet, addresses):
    """Bound COM reads to 256 rows per column instead of two calls per cell."""
    groups = {}
    for address in addresses:
        row, column = coordinate_to_tuple(address)
        groups.setdefault((column, (row - 1) // 256), []).append((row, address))
    result = {}
    for (column, _), cells in groups.items():
        first, last = min(r for r, _ in cells), max(r for r, _ in cells)
        letter = get_column_letter(column)
        values = sheet.Range(f'{letter}{first}:{letter}{last}').Value2
        for row, address in cells:
            value = values[row - first][0] if isinstance(values, tuple) else values
            # Excel/WPS represent worksheet errors as HRESULT integers. Only
            # these need a Text read; legitimate strings starting # stay strings.
            if isinstance(value, int) and not isinstance(value, bool) and -2146828290 <= value <= -2146826000:
                text = STANDARD_ERRORS.get(value & 0xFFFF)
                if text is None:
                    text = str(sheet.Range(address).Text)
                if text.startswith('#'):
                    value = text
            result[address] = value
    return result


def recalculate_formula_caches(path):
    path = Path(path).resolve()
    wb = load_workbook(path, data_only=False)
    positions = {ws.title: [c.coordinate for row in ws for c in row if c.data_type == 'f'] for ws in wb}
    wb.close()
    excel, engine = create_calculation_application()
    # Some WPS editions may reuse a process. Never change settings or Quit an
    # instance with an existing user workbook.
    if excel.Workbooks.Count:
        raise RuntimeError('办公软件未提供空闲独立计算实例，请保存工作后重试；现有工作簿未关闭')
    book = None
    values = {}
    try:
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 3
        book = excel.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True)
        calculate_all(excel, engine)
        for name, cells in positions.items():
            sheet = book.Worksheets(name)
            values[name] = read_formula_values(sheet, cells)
    finally:
        try:
            if book is not None:
                book.Close(SaveChanges=False)
        finally:
            excel.Quit()
    fd, temp = tempfile.mkstemp(prefix='recalc_', suffix='.xlsx', dir=path.parent)
    os.close(fd)
    try:
        with ZipFile(path) as source, ZipFile(temp, 'w') as target:
            rels = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(source.read('xl/_rels/workbook.xml.rels'))}
            parts = {}
            for sheet in ET.fromstring(source.read('xl/workbook.xml')).findall('x:sheets/x:sheet', NS):
                rel = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
                part = rels[rel]
                part = part.lstrip('/') if part.startswith('/') else posixpath.normpath('xl/' + part)
                parts[part] = values.get(sheet.attrib['name'], {})
            for item in source.infolist():
                data = source.read(item.filename)
                if parts.get(item.filename):
                    root = ET.fromstring(data)
                    for cell in root.findall('.//x:sheetData/x:row/x:c', NS):
                        address = cell.attrib.get('r')
                        if address not in parts[item.filename] or cell.find('x:f', NS) is None:
                            continue
                        value = parts[item.filename][address]
                        cached = cell.find('x:v', NS)
                        if cached is None:
                            cached = ET.SubElement(cell, '{' + NS['x'] + '}v')
                        if value is None:
                            cached.text = None
                            cell.attrib.pop('t', None)
                        elif isinstance(value, bool):
                            cell.set('t', 'b')
                            cached.text = '1' if value else '0'
                        elif isinstance(value, (int, float)):
                            cell.attrib.pop('t', None)
                            cached.text = str(value)
                        else:
                            cell.set('t', 'e' if str(value).startswith('#') else 'str')
                            cached.text = str(value)
                    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                target.writestr(item, data)
        with ZipFile(temp) as archive:
            if archive.testzip() is not None:
                raise ValueError('recalculated_zip_invalid')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
