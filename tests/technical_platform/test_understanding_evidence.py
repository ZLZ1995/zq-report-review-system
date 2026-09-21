"""K03 contract: EvidenceRef carries a bounded optional local summary."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

import xlwt
from pydantic import ValidationError

from asset_based_agent.agent_contracts import EvidenceRef, UnderstandingRequest
from asset_based_agent.technical_platform.skills import digest

SHA = 'a' * 64

SUMMARY = {
    'format': 'xls', 'readable': True, 'document_type': 'balance_sheet',
    'entity_name': 'A8T', 'period_start': None, 'period_end': '2026-07-31',
    'sheet_names': ['销项 1 (A8T)'], 'header_evidence': ['资产负债表', '期末余额'],
    'confidence': 0.98, 'warnings': ['期间仅识别到年月 2026-07，period_end 按月末规则推导为 2026-07-31'],
}


class EvidenceContractTest(unittest.TestCase):
    def test_legacy_request_without_evidence_still_valid(self):
        ref = EvidenceRef.model_validate({'id': 'f1', 'name': 'a.xlsx', 'sha256': SHA})
        self.assertIsNone(ref.evidence)
        self.assertNotIn('evidence', ref.model_dump())

    def test_summary_accepted_and_serialized(self):
        ref = EvidenceRef.model_validate({'id': 'f1', 'name': 'a.xls', 'sha256': SHA,
                                          'evidence': SUMMARY})
        self.assertEqual('balance_sheet', ref.evidence.document_type)
        dumped = ref.model_dump()
        self.assertEqual('A8T', dumped['evidence']['entity_name'])

    def test_unknown_summary_key_rejected(self):
        with self.assertRaises(ValidationError):
            EvidenceRef.model_validate({'id': 'f1', 'name': 'a.xls', 'sha256': SHA,
                                        'evidence': {**SUMMARY, 'path': '/tmp/secret'}})

    def test_unknown_document_type_rejected(self):
        with self.assertRaises(ValidationError):
            EvidenceRef.model_validate({'id': 'f1', 'name': 'a.xls', 'sha256': SHA,
                                        'evidence': {**SUMMARY, 'document_type': 'ledger'}})


class PrepareEvidenceTest(unittest.TestCase):
    def make_store(self, tmp):
        from asset_based_agent.technical_platform.store import PlatformStore
        return PlatformStore(Path(tmp) / 'db.sqlite', 'alice')

    def make_bs_xls(self, path):
        book = xlwt.Workbook()
        sheet = book.add_sheet('销项 1 (A8T)')
        sheet.write(0, 0, 'PRC-资产负债表')
        sheet.write(2, 0, '本期：2026-07')
        sheet.write(6, 0, '公司=A8T (阿里云飞天（北京）云计算有限公司)')
        hidden = book.add_sheet('XDO_METADATA')
        hidden.write(0, 0, 'SECRET-HIDDEN-TOKEN')
        hidden.visibility = 1
        book.save(str(path))

    def test_prepare_attaches_summary_for_workbooks(self):
        import tempfile
        from asset_based_agent.technical_platform.agent_controller import AgentController
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            project = store.create_project('one')
            session = store.create_session(project)
            source = Path(tmp) / 'A8T-BS202607.xls'
            self.make_bs_xls(source)
            identity = store.add_file(project, source, digest(source))
            controller = AgentController(store)
            pending = controller.prepare(session, '填报明细底稿', model_id='m',
                                         selected_ids=[identity])
            evidence = pending.request.files[0].evidence
            self.assertIsNotNone(evidence)
            self.assertEqual('balance_sheet', evidence.document_type)
            self.assertEqual('A8T', evidence.entity_name)
            self.assertEqual('2026-07-31', evidence.period_end)
            blob = pending.request.model_dump_json()
            self.assertNotIn(str(source), blob)
            self.assertNotIn('SECRET-HIDDEN-TOKEN', blob)
            self.assertNotIn('XDO_METADATA', blob)

    def test_prepare_leaves_other_files_without_summary(self):
        import tempfile
        from asset_based_agent.technical_platform.agent_controller import AgentController
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            project = store.create_project('one')
            session = store.create_session(project)
            source = Path(tmp) / 'notes.txt'
            source.write_text('plain', encoding='utf-8')
            identity = store.add_file(project, source, digest(source))
            controller = AgentController(store)
            pending = controller.prepare(session, '说明', model_id='m', selected_ids=[identity])
            self.assertIsNone(pending.request.files[0].evidence)


if __name__ == '__main__':
    unittest.main()
