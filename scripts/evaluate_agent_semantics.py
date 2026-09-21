"""Score saved semantic observations only; no network calls and no release approval."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_bounded(path):
    with path.open('rb') as stream:
        raw = stream.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError('Semantic evidence file exceeds 10MB')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--cases', type=Path, action='append')
    source.add_argument('--frozen-corpus', type=Path)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from asset_based_agent.technical_platform.project_catalog import (
        validate_business_directory,
    )
    destination = args.output.resolve()
    validate_business_directory(destination.parent)
    if destination.exists():
        raise FileExistsError('Choose a new report filename; existing evidence is never overwritten')
    scorer = ROOT / 'tests' / 'agent_acceptance' / 'scoring.py'
    spec = importlib.util.spec_from_file_location('agent_semantic_scoring', scorer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    corpus_path = ROOT / 'tests' / 'agent_acceptance' / 'corpus.py'
    corpus_spec = importlib.util.spec_from_file_location('agent_semantic_corpus', corpus_path)
    corpus = importlib.util.module_from_spec(corpus_spec)
    corpus_spec.loader.exec_module(corpus)
    cases, hashes = [], []
    if args.frozen_corpus:
        cases = corpus.load_corpus(args.frozen_corpus)
        # Execute only the repository loader, never code from the supplied folder.
        if (args.frozen_corpus.parent / 'corpus.py').read_bytes() != corpus_path.read_bytes():
            raise ValueError('Frozen corpus expander differs from the trusted loader')
    for path in args.cases or []:
        raw = read_bounded(path)
        for line in raw.decode('utf-8-sig').splitlines():
            if not line.strip():
                continue
            row = json.loads(line, object_pairs_hook=corpus.unique_object)
            cases.append(corpus.expand_case(row, category=path.stem,
                split='holdout' if path.stem == 'holdout' else 'base') if 'expect' in row else row)
        hashes.append(hashlib.sha256(raw).hexdigest())
    raw = read_bounded(args.observations)
    report = module.summarize(cases, json.loads(raw, object_pairs_hook=corpus.unique_object))
    report['evidence_sha256'] = {'cases': hashes, 'observations': hashlib.sha256(raw).hexdigest(),
                                'scorer': hashlib.sha256(scorer.read_bytes()).hexdigest(),
                                'corpus_expander': hashlib.sha256(corpus_path.read_bytes()).hexdigest()}
    report['frozen_corpus_verified'] = bool(args.frozen_corpus)
    if args.frozen_corpus:
        report['evidence_sha256']['corpus_manifest'] = hashlib.sha256(
            read_bounded(args.frozen_corpus / 'manifest.json')).hexdigest()
    report['evaluation_mode'] = 'offline_labels_only'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print('Offline label scoring written; live-model and release acceptance remain unverified.')
    return 0 if report['automatic_label_gate'] else 2


if __name__ == '__main__':
    sys.exit(main())
