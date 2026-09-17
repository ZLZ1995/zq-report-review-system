import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from test_semantic_scoring import scoring


def loader():
    path = Path(__file__).resolve().parents[1] / 'agent_acceptance' / 'corpus.py'
    spec = importlib.util.spec_from_file_location('semantic_corpus', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_has_independent_inputs_explicit_scopes_and_holdout():
    cases = loader().load_corpus()
    assert Counter(c['split'] for c in cases) == {'base': 100, 'holdout': 20}
    assert Counter(c['category'] for c in cases if c['split'] == 'base') == {
        'intent': 20, 'dialogue': 20, 'scope': 20, 'permissions': 20, 'recovery': 20}
    assert len({c['input_sha256'] for c in cases}) == 120
    for case in cases:
        scoring().validate_case(case)
        files = {f['id'] for f in case['input']['files']}
        assert set(case['expected']['targets'] + case['expected']['references'] + case['expected']['excluded']) <= files
        assert case['manual_checks'] and case['input']['prompt']
    assert any(c.get('required_capabilities') == ['browser.interact'] for c in cases)
    result = scoring().summarize(cases, {})
    assert result['coverage_gate'] and result['automatic_accuracy'] == 0
    assert not result['automatic_label_gate'] and not result['release_accepted']


def test_cli_scores_compact_corpus_without_fabricating_responses(tmp_path, monkeypatch):
    import json

    from test_acceptance_runner import load_script
    corpus = loader()
    module = load_script('evaluate_agent_semantics')
    observed = tmp_path / 'observed.json'
    observed.write_text('{}', encoding='utf-8')
    report = tmp_path / 'report.json'
    argv = ['evaluate', '--observations', str(observed), '--output', str(report)]
    for name in ('intent', 'dialogue', 'scope', 'permissions', 'recovery', 'holdout'):
        argv.extend(['--cases', str(corpus.ROOT / (name + '.jsonl'))])
    monkeypatch.setattr(module.sys, 'argv', argv)
    assert module.main() == 2
    result = json.loads(report.read_text('utf-8'))
    assert result['counts_by_split'] == {'base': 100, 'holdout': 20}
    assert all(r['mismatches'] == ['missing_observation'] for r in result['results'])
    assert 'corpus_expander' in result['evidence_sha256']


def test_frozen_corpus_rejects_unrecorded_edits(tmp_path):
    import shutil
    corpus = loader()
    copied = tmp_path / 'acceptance'
    shutil.copytree(corpus.ROOT, copied / 'cases')
    shutil.copyfile(corpus.ROOT.parent / 'corpus.py', copied / 'corpus.py')
    assert len(corpus.load_corpus(copied / 'cases')) == 120
    target = copied / 'cases' / 'holdout.jsonl'
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='freeze'):
        corpus.load_corpus(copied / 'cases')


def test_cli_frozen_mode_verifies_manifest_before_writing(tmp_path, monkeypatch):
    import json
    import shutil

    from test_acceptance_runner import load_script
    corpus = loader()
    module = load_script('evaluate_agent_semantics')
    copied = tmp_path / 'acceptance'
    shutil.copytree(corpus.ROOT, copied / 'cases')
    shutil.copyfile(corpus.ROOT.parent / 'corpus.py', copied / 'corpus.py')
    observed = tmp_path / 'observed.json'
    observed.write_text('{}', encoding='utf-8')
    report = tmp_path / 'report.json'
    monkeypatch.setattr(module.sys, 'argv', ['evaluate', '--frozen-corpus', str(copied / 'cases'),
        '--observations', str(observed), '--output', str(report)])
    target = copied / 'cases' / 'holdout.jsonl'
    original = target.read_bytes()
    target.write_bytes(original + b'\n')
    with pytest.raises(ValueError, match='freeze'):
        module.main()
    assert not report.exists()
    target.write_bytes(original)
    assert module.main() == 2
    result = json.loads(report.read_text('utf-8'))
    assert result['frozen_corpus_verified'] is True
    assert 'corpus_manifest' in result['evidence_sha256']
    assert not result['release_accepted']
