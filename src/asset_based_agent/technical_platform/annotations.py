"""Conservative DOCX comment copies; unsupported anchors are never guessed."""
import json
import threading
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from lxml import etree as ET
from PySide6.QtCore import QThread

from .excel_annotations import annotate_excel
from .skills import digest

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'w': W}


def annotation_offer(state, result):
    return state == 'succeeded' and result.get('kind') == 'review' and bool(result.get('issues'))


def default_selected(issue):
    return issue.get('status') != 'ignored' and (
        issue.get('requires_verification') is True or issue.get('nature') in {'confirmed', 'uncertain'}
        or issue.get('evidence_state') == 'verified')


def _xml(raw):
    return ET.fromstring(raw, parser=ET.XMLParser(resolve_entities=False, no_network=True))


def _bytes(root):
    return ET.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)


def annotate_docx(source, destination, issues):
    """Accept only unique exact paragraphs consisting of plain text runs."""
    with ZipFile(source) as archive:
        entries = {item.filename: archive.read(item) for item in archive.infolist()}
        infos = archive.infolist()
    if any(name.startswith('_xmlsignatures/') for name in entries):
        raise ValueError('数字签名文档不支持标注')
    document = _xml(entries['word/document.xml'])
    comments_path = 'word/comments.xml'
    rels_path = 'word/_rels/document.xml.rels'
    rels = _xml(entries[rels_path]) if rels_path in entries else ET.Element(f'{{{R}}}Relationships')
    relations = [r for r in rels if r.get('Type', '').endswith('/comments')]
    if relations and relations[0].get('Target') != 'comments.xml':
        raise ValueError('当前批注部件布局暂不支持，已保留原文件')
    comments = _xml(entries[comments_path]) if comments_path in entries else ET.Element(f'{{{W}}}comments', nsmap={'w': W})
    identifier = max([int(c.get(f'{{{W}}}id', '0')) for c in comments] + [-1]) + 1
    applied, skipped = [], []
    for number, issue in issues:
        quote = issue.get('original_text', '').strip()
        matches = [p for p in document.findall('.//w:body/w:p', NS)
                   if ''.join(p.itertext()).strip() == quote] if quote else []
        if len(matches) != 1:
            skipped.append({'issue': number, 'reason': '缺少唯一可验证的完整原文段落；未猜测位置'})
            continue
        paragraph = matches[0]
        runs = paragraph.findall('w:r', NS)
        allowed = {f'{{{W}}}pPr', f'{{{W}}}r'}
        if not runs or any(child.tag not in allowed for child in paragraph) or any(
            child.tag not in {f'{{{W}}}rPr', f'{{{W}}}t'} for run in runs for child in run):
            skipped.append({'issue': number, 'reason': '段落含字段、已有锚点或复杂对象，暂不标注'})
            continue
        comment = ET.SubElement(comments, f'{{{W}}}comment', {f'{{{W}}}id': str(identifier), f'{{{W}}}author': 'ZQ'})
        text = ET.SubElement(ET.SubElement(ET.SubElement(comment, f'{{{W}}}p'), f'{{{W}}}r'), f'{{{W}}}t')
        nature = '待核实' if issue.get('requires_verification') else '审核意见（请核对）'
        text.text = f"{number}｜{nature}：{issue['description']} 建议：{issue.get('recommendation', '')}"
        for run in runs:
            props = run.find('w:rPr', NS)
            if props is None:
                props = ET.Element(f'{{{W}}}rPr')
                run.insert(0, props)
            highlight = props.find('w:highlight', NS)
            if highlight is None:
                highlight = ET.SubElement(props, f'{{{W}}}highlight')
            highlight.set(f'{{{W}}}val', 'yellow')
        start = ET.Element(f'{{{W}}}commentRangeStart', {f'{{{W}}}id': str(identifier)})
        end = ET.Element(f'{{{W}}}commentRangeEnd', {f'{{{W}}}id': str(identifier)})
        paragraph.insert(paragraph.index(runs[0]), start)
        paragraph.append(end)
        ref = ET.SubElement(paragraph, f'{{{W}}}r')
        ET.SubElement(ref, f'{{{W}}}commentReference', {f'{{{W}}}id': str(identifier)})
        applied.append(number)
        identifier += 1
    if not applied:
        return [], skipped
    if not relations:
        ET.SubElement(rels, f'{{{R}}}Relationship', Id='zq' + uuid4().hex,
                      Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments', Target='comments.xml')
    content_types = _xml(entries['[Content_Types].xml'])
    if not any(x.get('PartName') == '/word/comments.xml' for x in content_types):
        ET.SubElement(content_types, f'{{{CT}}}Override', PartName='/word/comments.xml',
                      ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml')
    changed = {'word/document.xml': _bytes(document), comments_path: _bytes(comments),
               rels_path: _bytes(rels), '[Content_Types].xml': _bytes(content_types)}
    # Same text, existing comment XML retained, every unrelated ZIP member copied byte-for-byte.
    assert document.xpath('//w:t/text()', namespaces=NS) == _xml(entries['word/document.xml']).xpath('//w:t/text()', namespaces=NS)
    with ZipFile(destination, 'x') as archive:
        for info in infos:
            archive.writestr(info, changed.get(info.filename, entries[info.filename]))
        for name, raw in changed.items():
            if name not in entries:
                archive.writestr(name, raw)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(archive.read(name) == raw for name, raw in entries.items() if name not in changed)
    return applied, skipped


def generate_annotations(store, run_id, selected, directory, cancel=None):
    run = store.run(run_id)
    result = json.loads(run['result'] or '{}')
    if not annotation_offer(run['state'], result):
        raise ValueError('仅完整审核且有问题的任务可以生成批注副本')
    files = json.loads(run['snapshot'])['files']
    directory = Path(directory).resolve()
    from .project_catalog import validate_business_directory
    validate_business_directory(directory)
    if not directory.is_dir():
        raise ValueError('请选定已存在的保存目录')
    selected = set(selected)
    if not selected or not selected <= set(range(1, len(result['issues']) + 1)):
        raise ValueError('请选择有效的本轮问题')
    records, artifacts = [], []
    known_ids = {f['id'] for f in files}
    records.extend({'issue': n, 'reason': '问题不属于本轮已核实的文件清单，未标注'}
                   for n, item in enumerate(result['issues'], 1)
                   if n in selected and item.get('source_file_id') not in known_ids)
    for file in files:
        if cancel is not None and cancel.is_set():
            break
        issues = [(n, issue) for n, issue in enumerate(result['issues'], 1)
                  if n in selected and issue.get('source_file_id') == file['id']]
        if not issues:
            continue
        source = Path(file['path'])
        if digest(source) != file['sha256']:
            raise ValueError('资料版本已变化，请重新审核')
        if source.suffix.lower() not in {'.docx', '.xlsx', '.xlsm'}:
            records.extend({'issue': n, 'reason': '此格式暂未接入保真标注执行器，未修改'} for n, _ in issues)
            continue
        destination = directory / f'{source.stem}_标注版_{uuid4().hex[:10]}{source.suffix}'
        try:
            writer = annotate_docx if source.suffix.lower() == '.docx' else annotate_excel
            applied, skipped = writer(source, destination, issues)
            if digest(source) != file['sha256']:
                raise ValueError('原件校验失败')
            records.extend(skipped)
            records.extend({'issue': n, 'reason': '已标注'} for n in applied)
            if applied:
                artifacts.append(str(destination))
        except FileExistsError:
            records.extend({'issue': n, 'reason': '输出文件已存在，未覆盖'} for n, _ in issues)
        except Exception:  # noqa: BLE001 - per-file boundary withholds failed copies
            destination.unlink(missing_ok=True)
            records.extend({'issue': n, 'reason': '文件写入或保真校验失败，未交付此副本'} for n, _ in issues)
    result.setdefault('annotations', []).append({'records': records, 'files': artifacts})
    from .delivery_versions import record_delivery
    for artifact in artifacts:
        record_delivery(result, artifact)
    store.save_result(run_id, result)
    return records, artifacts


class AnnotationWorker(QThread):
    def __init__(self, store, run_id, selected, directory, parent=None):
        super().__init__(parent)
        self.cancel = threading.Event()
        self.store, self.run_id, self.selected, self.directory = store, run_id, selected, directory
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = generate_annotations(self.store, self.run_id, self.selected, self.directory, self.cancel)
        except Exception:  # noqa: BLE001 - do not expose document contents in errors
            self.error = '批注未完成，请检查本轮文件版本、保存位置和文件格式；原件未被覆盖。'
