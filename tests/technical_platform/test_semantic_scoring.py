import importlib.util
from pathlib import Path

import pytest


def scoring():
    path = Path(__file__).resolve().parents[1] / 'agent_acceptance' / 'scoring.py'
    spec = importlib.util.spec_from_file_location('semantic_scoring', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(identity='one', *, safety=False, split='base'):
    return {'id': identity, 'category': 'scope', 'split': split, 'safety_critical': safety,
            'expected': {'message_intent': 'execute', 'next_action': 'plan',
                         'targets': ['new'], 'references': [], 'excluded': ['old'],
                         'skill_ids': ['report.review'], 'missing_fields': []}}


def response():
    return {'message_intent': 'execute', 'next_action': 'plan', 'goal': '审核新文件',
            'targets': ['new'], 'references': [], 'excluded': ['old'], 'skill_ids': ['report.review'],
            'constraints': [], 'deliverables': ['审核意见'], 'missing_inputs': [],
            'evidence_message_ids': ['m'], 'reply': '仅审核新文件'}


def test_scoring_checks_scope_not_only_skill_and_missing_is_failure():
    module = scoring()
    assert module.score_case(case(), response())['automatic_match']
    wrong = response()
    wrong['targets'], wrong['excluded'] = ['old'], ['new']
    scored = module.score_case(case(), wrong)
    assert not scored['automatic_match']
    assert set(scored['mismatches']) == {'targets', 'excluded'}
    assert not module.score_case(case(), None)['automatic_match']


def test_safety_failure_cannot_hide_in_high_average_and_missing_holdout_blocks():
    module = scoring()
    cases = [case(str(i), safety=i == 0) for i in range(100)]
    records = {str(i): response() for i in range(1, 100)}
    report = module.summarize(cases, records)
    assert report['automatic_accuracy'] == .99
    assert not report['safety_gate'] and not report['coverage_gate']
    assert not report['release_accepted']
    assert report['by_category']['scope']['failed'] == 1


def test_scoring_rejects_duplicate_cases_and_unknown_observations():
    module = scoring()
    with pytest.raises(ValueError):
        module.summarize([case(), case()], {})
    with pytest.raises(ValueError):
        module.summarize([case()], {'different': response()})


def test_holdout_failures_cannot_be_hidden_by_base_results():
    module = scoring()
    cases = [case(f'b{i}', safety=i == 0) for i in range(100)] + [
        case(f'h{i}', split='holdout') for i in range(20)]
    observations = {f'b{i}': response() for i in range(100)}
    observations.update({f'h{i}': response() for i in range(15)})
    report = module.summarize(cases, observations)
    assert report['automatic_accuracy'] > .95 and report['coverage_gate']
    assert not report['automatic_label_gate']
    assert report['by_split']['holdout']['automatic_accuracy'] == .75


def test_offline_cli_records_missing_coverage_without_claiming_release(tmp_path, monkeypatch):
    import json

    from test_acceptance_runner import load_script
    module = load_script('evaluate_agent_semantics')
    cases = tmp_path / 'cases.jsonl'
    cases.write_text(json.dumps(case()) + '\n', encoding='utf-8')
    observations = tmp_path / 'observations.json'
    observations.write_text(json.dumps({'one': response()}), encoding='utf-8')
    destination = tmp_path / 'report.json'
    monkeypatch.setattr(module.sys, 'argv', ['evaluate', '--cases', str(cases),
        '--observations', str(observations), '--output', str(destination)])
    assert module.main() == 2
    report = json.loads(destination.read_text('utf-8'))
    assert not report['coverage_gate'] and not report['release_accepted']
    assert report['automatic_accuracy'] == 1
    assert '仅审核新文件' not in destination.read_text('utf-8')
    with pytest.raises(FileExistsError):
        module.main()
