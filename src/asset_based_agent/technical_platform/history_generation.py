"""Fill the approved history template's repeating event blocks only."""
import hashlib
import json
import runpy
from copy import deepcopy
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree


def validate_text_format(document, template):
    """Require explicit fonts and sizes; absent properties cannot pass vacuously."""
    font_keys = ('eastAsia', 'ascii', 'hAnsi', 'cs')

    def signature(run):
        nodes = run.xpath('./w:rPr/w:rFonts')
        if not nodes:
            return None
        return tuple(nodes[0].get(qn('w:' + key)) for key in font_keys)

    prototypes = {False: set(), True: set()}
    for p in template._element.body.iter(qn('w:p')):
        in_table = any(a.tag == qn('w:tc') for a in p.iterancestors())
        prototypes[in_table].update(signature(r) for r in p.xpath('./w:r[w:t]'))
    for values in prototypes.values():
        values.discard(None)
    fonts_ok = sizes_ok = indent_ok = True
    for p in document._element.body.iter(qn('w:p')):
        in_table = any(a.tag == qn('w:tc') for a in p.iterancestors())
        expected = '18' if in_table else '24'
        for r in p.xpath('./w:r[w:t]'):
            fonts_ok &= signature(r) in prototypes[in_table]
            sizes_ok &= all(r.xpath(f'./w:rPr/w:{tag}/@w:val') == [expected]
                            for tag in ('sz', 'szCs'))
        indent_ok &= p.xpath('./w:pPr/w:ind/@w:firstLineChars') == ['0' if in_table else '200']
        indent_ok &= not bool(p.xpath('./w:pPr/w:ind/@w:hanging | ./w:pPr/w:ind/@w:hangingChars'))
    return [{'id': name, 'ok': bool(ok)} for name, ok in (
        ('template_fonts_preserved', fonts_ok), ('text_size', sizes_ok),
        ('first_line_indent', indent_ok))]


def generate(scripts, inputs, output):
    builder = runpy.run_path(str(scripts / 'build_gongshang_docx.py'))
    validator = runpy.run_path(str(scripts / 'build_history_fragment.py'))
    template = inputs['template']
    source = inputs['source_excel']
    document = Document(template)
    original = Document(template)
    slots = [p for p in document.paragraphs if '【变更日期】' in p.text and '【变更事项】' in p.text]
    if len(slots) != 5 or [len(t.columns) for t in document.tables] != [7, 7, 7, 3, 7]:
        raise ValueError('工商模板占位布局不匹配，禁止套用其他版式')
    # The locked template has five example event blocks; static content outside
    # these paragraph/table/spacer blocks remains untouched.
    removable = []
    for p in slots:
        table = p._p.getnext()
        spacer = table.getnext() if table is not None else None
        if table is None or table.tag != qn('w:tbl') or spacer is None or spacer.tag != qn('w:p'):
            raise ValueError('工商模板事件块边界异常')
        if ''.join(spacer.itertext()).strip():
            raise ValueError('工商模板事件间隔含固定内容，禁止删除')
        removable.extend([p._p, table, spacer])
    raw = builder['load_events'](source)
    plan = builder['table_plan_for_events'](raw)
    plan = [e for e in plan if e['equity'] or e['normal']]
    body = document._element.body
    anchor = slots[0]._p
    for i, entry in enumerate(plan, 1):
        element = deepcopy(original.paragraphs[0]._p)
        anchor.addprevious(element)
        paragraph = Paragraph(element, document)
        builder['replace_paragraph_text'](paragraph, builder['describe_plan_event'](i, entry))
        paragraph.paragraph_format.keep_with_next = True
        builder['build_planned_tables'](document, entry, original.tables[0], original.tables[3], element)
    if not plan:
        element = deepcopy(original.paragraphs[0]._p)
        anchor.addprevious(element)
        builder['replace_paragraph_text'](Paragraph(element, document), '本次资料未检出需要披露的实质工商变更事项。')
    for element in removable:
        body.remove(element)
    builder['apply_document_text_format'](document)
    staged = output / 'history_staging.docx'
    # Preserve every other template ZIP member byte-for-byte (styles, headers,
    # footers, relationships, document settings and section resources).
    with ZipFile(template) as src, ZipFile(staged, 'w') as dst:
        for item in src.infolist():
            data = etree.tostring(document._element, encoding='UTF-8', xml_declaration=True, standalone=True) if item.filename == 'word/document.xml' else src.read(item.filename)
            dst.writestr(item, data)
    events = [{'date': e['date'], 'description': builder['describe_plan_event'](i, e),
               'equity_rows': e['equity'], 'normal_rows': e['normal']} for i, e in enumerate(plan, 1)]
    validation = validator['validate_events'](events, staged)
    reopened = Document(staged)
    def check(name, ok):
        validation['checks'].append({'id': name, 'ok': bool(ok)})
    check('events_order_correct', [e['date'] for e in events] == sorted(e['date'] for e in events))
    check('event_tables_count', len(reopened.tables) == len(events))
    for table, event in zip(reopened.tables, events):
        check('table_column_shape', len(table.columns) == (7 if event['equity_rows'] else 3))
        text = '\n'.join(c.text for r in table.rows for c in r.cells)
        for row in event['equity_rows'] + event['normal_rows']:
            check('saved_table_values', all(str(v) in text for k, v in row.items() if k != 'kind' and v))
    validation['checks'].extend(validate_text_format(reopened, original))
    check('placeholder_removed', '【变更日期】' not in '\n'.join(p.text for p in reopened.paragraphs))
    validation['ok'] = all(c['ok'] for c in validation['checks'])
    final = output / 'history_fragment.docx'
    validation['outputs'] = {'history_fragment_docx': str(final) if validation['ok'] else None}
    with open(source, 'rb') as source_file:
        source_hash = hashlib.sha256(source_file.read()).hexdigest()
    (output / 'history_events.json').write_text(json.dumps({'events': events, 'source_sha256': source_hash}, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'history_validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding='utf-8')
    if not validation['ok']:
        raise ValueError('工商生成后回读验收失败，详见 history_validation.json')
    staged.replace(final)
    (output / 'user_feedback.md').write_text(f'已按锁定模板生成工商历史沿革，共 {len(events)} 个披露事件。\n来源原件未修改；字号、首行缩进、事件及表格内容已回读校验。\n', encoding='utf-8')
    return True
