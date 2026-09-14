"""Calculate in read-only Excel, then update OOXML caches without replacing formulas."""
import os
import posixpath
import tempfile
from lxml import etree as ET
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def recalculate_formula_caches(path):
    import win32com.client as win32
    path = Path(path).resolve()
    wb = load_workbook(path, data_only=False)
    positions = {ws.title: [c.coordinate for row in ws for c in row if c.data_type == 'f'] for ws in wb}
    wb.close()
    excel = win32.DispatchEx('Excel.Application')
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AutomationSecurity = 3
    book = None
    values = {}
    try:
        book = excel.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True)
        excel.CalculateFullRebuild()
        for name, cells in positions.items():
            sheet = book.Worksheets(name)
            values[name] = {}
            for address in cells:
                cell = sheet.Range(address)
                value = cell.Value2
                # Excel errors arrive as integer HRESULT values; use displayed error text.
                text = str(cell.Text)
                values[name][address] = text if text.startswith(('#REF!', '#VALUE!', '#DIV/0!', '#NAME?', '#N/A', '#NUM!', '#SPILL!', '#CALC!')) else value
    finally:
        if book is not None:
            book.Close(SaveChanges=False)
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
